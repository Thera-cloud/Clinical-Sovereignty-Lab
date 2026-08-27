import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart' show kIsWeb, defaultTargetPlatform, TargetPlatform;
import 'package:http/http.dart' as http;
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:logger/logger.dart';

import '../config/app_config.dart';
import 'payment_service.dart';

/// StoreKit purchase path for native iOS (Guideline 3.1.1).
class IapService {
  IapService._();
  static final IapService instance = IapService._();

  final _logger = Logger();
  final InAppPurchase _iap = InAppPurchase.instance;

  StreamSubscription<List<PurchaseDetails>>? _sub;
  final Map<String, ProductDetails> _products = {};
  Completer<PurchaseStatusResult>? _pending;
  String? _pendingProductId;
  String? _userId;
  String? _authToken;
  bool _ready = false;

  static const sanctuaryBase = 'net.sovereignsanctuary.sanctuary_charge_base_fee';
  static const sanctuaryAssisted = 'net.sovereignsanctuary.sanctuary_charge_assisted_response';
  static const sanctuaryGroup = 'net.sovereignsanctuary.sanctuary_charge_group_coaching';
  static const sanctuaryIndividual = 'net.sovereignsanctuary.sanctuary_charge_individual_coaching';

  static const Set<String> sanctuaryIds = {
    sanctuaryBase,
    sanctuaryAssisted,
    sanctuaryGroup,
    sanctuaryIndividual,
  };

  static Set<String> get allProductIds => {
        ...PaymentService.productIds,
        ...sanctuaryIds,
      };

  bool get isNativeIOS =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.iOS;

  ProductDetails? product(String id) => _products[id];

  String? priceLabel(String id) => _products[id]?.price;

  Future<void> initialize() async {
    if (!isNativeIOS || _ready) return;
    final available = await _iap.isAvailable();
    if (!available) {
      _logger.w('IapService: StoreKit unavailable');
      return;
    }
    _sub ??= _iap.purchaseStream.listen(
      _onPurchases,
      onError: (Object e) {
        _logger.e('IapService: purchase stream error', error: e);
        _failPending(e.toString());
      },
    );
    await loadProducts();
    _ready = true;
  }

  Future<void> loadProducts() async {
    if (!isNativeIOS) return;
    final resp = await _iap.queryProductDetails(allProductIds);
    for (final p in resp.productDetails) {
      _products[p.id] = p;
    }
    if (resp.notFoundIDs.isNotEmpty) {
      _logger.w('IapService: products not found: ${resp.notFoundIDs}');
    }
  }

  Future<PurchaseStatusResult> purchase(
    String productId, {
    required String userId,
    required String authToken,
  }) async {
    await initialize();
    if (!_ready) {
      return PurchaseStatusResult(
        productId: productId,
        status: PaymentStatus.error,
        error: 'In-App Purchase is unavailable on this device',
      );
    }
    var details = _products[productId];
    if (details == null) {
      await loadProducts();
      details = _products[productId];
    }
    if (details == null) {
      return PurchaseStatusResult(
        productId: productId,
        status: PaymentStatus.error,
        error: 'Product not found in App Store',
      );
    }
    if (_pending != null && !_pending!.isCompleted) {
      return PurchaseStatusResult(
        productId: productId,
        status: PaymentStatus.error,
        error: 'A purchase is already in progress',
      );
    }

    _userId = userId;
    _authToken = authToken;
    _pendingProductId = productId;
    _pending = Completer<PurchaseStatusResult>();

    final param = PurchaseParam(productDetails: details);
    final isSub = PaymentService.subscriptionIds.contains(productId);
    try {
      final ok = isSub
          ? await _iap.buyNonConsumable(purchaseParam: param)
          : await _iap.buyConsumable(purchaseParam: param);
      if (!ok) {
        return _completePending(PurchaseStatusResult(
          productId: productId,
          status: PaymentStatus.error,
          error: 'Could not start App Store purchase',
        ));
      }
    } catch (e) {
      return _completePending(PurchaseStatusResult(
        productId: productId,
        status: PaymentStatus.error,
        error: e.toString(),
      ));
    }

    return _pending!.future.timeout(
      const Duration(minutes: 3),
      onTimeout: () => _completePending(PurchaseStatusResult(
        productId: productId,
        status: PaymentStatus.error,
        error: 'Purchase timed out',
      )),
    );
  }

  Future<void> restorePurchases({String? userId, String? authToken}) async {
    _userId = userId ?? _userId;
    _authToken = authToken ?? _authToken;
    await initialize();
    await _iap.restorePurchases();
  }

  Future<void> _onPurchases(List<PurchaseDetails> purchases) async {
    for (final p in purchases) {
      if (p.status == PurchaseStatus.pending) continue;
      if (p.status == PurchaseStatus.canceled) {
        _failPending('Purchase canceled', canceled: true);
        if (p.pendingCompletePurchase) {
          await _iap.completePurchase(p);
        }
        continue;
      }
      if (p.status == PurchaseStatus.error) {
        _failPending(p.error?.message ?? 'Purchase failed');
        if (p.pendingCompletePurchase) {
          await _iap.completePurchase(p);
        }
        continue;
      }
      if (p.status == PurchaseStatus.purchased ||
          p.status == PurchaseStatus.restored) {
        final verified = await _verifyApple(p);
        if (verified && p.pendingCompletePurchase) {
          await _iap.completePurchase(p);
        }
        if (verified) {
          _completePending(PurchaseStatusResult(
            productId: p.productID,
            status: p.status == PurchaseStatus.restored
                ? PaymentStatus.restored
                : PaymentStatus.purchased,
          ));
        } else {
          _failPending('Receipt verification failed');
        }
      }
    }
  }

  Future<bool> _verifyApple(PurchaseDetails p) async {
    final token = _authToken ?? '';
    final uid = _userId ?? '';
    if (token.isEmpty || uid.isEmpty) {
      _logger.e('IapService: missing auth context for receipt verify');
      return false;
    }
    final receipt = p.verificationData.serverVerificationData;
    if (receipt.isEmpty) {
      _logger.e('IapService: empty Apple receipt');
      return false;
    }
    final baseUrl = AppConfig.apiBaseUrl
        .replaceAll(RegExp(r'/api/?$'), '')
        .replaceAll(RegExp(r'/+$'), '');
    try {
      final resp = await http
          .post(
            Uri.parse('$baseUrl/api/billing/verify-receipt/apple'),
            headers: {
              'Content-Type': 'application/json',
              'Authorization': 'Bearer $token',
            },
            body: jsonEncode({
              'receipt_data': receipt,
              'user_id': uid,
              'product_id': p.productID,
            }),
          )
          .timeout(const Duration(seconds: 30));
      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        return true;
      }
      _logger.w('IapService: verify failed ${resp.statusCode} ${resp.body}');
      return false;
    } catch (e, st) {
      _logger.e('IapService: verify exception', error: e, stackTrace: st);
      return false;
    }
  }

  PurchaseStatusResult _completePending(PurchaseStatusResult result) {
    final c = _pending;
    _pending = null;
    _pendingProductId = null;
    if (c != null && !c.isCompleted) {
      c.complete(result);
    }
    return result;
  }

  void _failPending(String message, {bool canceled = false}) {
    _completePending(PurchaseStatusResult(
      productId: _pendingProductId ?? '',
      status: canceled ? PaymentStatus.canceled : PaymentStatus.error,
      error: message,
    ));
  }
}
