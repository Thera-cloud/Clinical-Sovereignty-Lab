import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart' show kIsWeb, defaultTargetPlatform, TargetPlatform;
import 'package:http/http.dart' as http;
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:in_app_purchase_storekit/in_app_purchase_storekit.dart';
import 'package:logger/logger.dart';

import '../config/app_config.dart';
import 'payment_service.dart';

/// StoreKit purchase path for native iOS (Guideline 3.1.1).
class IapService {
  IapService._();
  static final IapService instance = IapService._();

  final _logger = Logger();
  InAppPurchase? _iapClient;
  Future<void>? _initializing;
  InAppPurchase get _iap => _iapClient!;

  StreamSubscription<List<PurchaseDetails>>? _sub;
  final Map<String, ProductDetails> _products = {};
  final Map<String, PurchaseDetails> _deferredPurchases = {};
  Future<void> _purchaseEventChain = Future<void>.value();
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
    final activeInitialization = _initializing;
    if (activeInitialization != null) {
      await activeInitialization;
      return;
    }
    final initialization = _initializeStoreKit();
    _initializing = initialization;
    try {
      await initialization;
    } finally {
      if (!_ready) _initializing = null;
    }
  }

  Future<void> _initializeStoreKit() async {
    // The backend validates App Store receipts with verifyReceipt, which
    // requires the base64 app receipt exposed by StoreKit 1. This must finish
    // before InAppPurchase.instance registers the platform implementation.
    await InAppPurchaseStoreKitPlatform.enableStoreKit1();
    _iapClient ??= InAppPurchase.instance;
    final available = await _iap.isAvailable();
    if (!available) {
      _logger.w('IapService: StoreKit unavailable');
      return;
    }
    _sub ??= _iap.purchaseStream.listen(
      (purchases) {
        // StoreKit can replay unfinished transactions at launch. Process every
        // batch serially so verification and completePurchase never race.
        _purchaseEventChain = _purchaseEventChain
            .then((_) => _onPurchases(purchases))
            .catchError((Object e, StackTrace st) {
        _logger.e('IapService: purchase processing failed',
              error: e, stackTrace: st);
          _failPending('The App Store purchase could not be finalized. '
              'Please tap Restore Purchases and try again.');
        });
      },
      onError: (Object e) {
        _logger.e('IapService: purchase stream error', error: e);
        _failPending('The App Store connection was interrupted. '
            'Please tap Restore Purchases and try again.');
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
    // Set auth before subscribing to StoreKit. StoreKit may immediately replay
    // an unfinished transaction that must be verified and completed first.
    _userId = userId;
    _authToken = authToken;
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
        error: 'This product is not available in the App Store yet. '
            'Use Restore Purchases if you already bought it.',
      );
    }
    await _purchaseEventChain;
    final recovered = await _retryDeferredPurchase(productId);
    if (recovered != null) return recovered;

    if (_pending != null && !_pending!.isCompleted) {
      return PurchaseStatusResult(
        productId: productId,
        status: PaymentStatus.error,
        error: 'A purchase is already in progress',
      );
    }

    _pendingProductId = productId;
    final pending = Completer<PurchaseStatusResult>();
    _pending = pending;
    var recoveringDuplicate = false;

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
      if (_isDuplicateTransactionError(e)) {
        recoveringDuplicate = true;
        _logger.w('IapService: recovering unfinished $productId transaction');
        try {
          // This re-emits the existing StoreKit transaction through the
          // purchase stream, where it is verified and completed.
          await _iap.restorePurchases();
        } catch (restoreError, st) {
          _logger.e('IapService: duplicate recovery failed',
              error: restoreError, stackTrace: st);
          return _completePending(PurchaseStatusResult(
        productId: productId,
        status: PaymentStatus.error,
        error: 'A previous purchase is still being finalized. '
                'Please tap Restore Purchases, then try again.',
          ));
        }
      } else {
        return _completePending(PurchaseStatusResult(
          productId: productId,
          status: PaymentStatus.error,
          error: _safePurchaseError(e),
        ));
      }
    }

    return pending.future.timeout(
      recoveringDuplicate
          ? const Duration(seconds: 30)
          : const Duration(minutes: 3),
      onTimeout: () => _completePending(PurchaseStatusResult(
        productId: productId,
        status: PaymentStatus.error,
        error: recoveringDuplicate
            ? 'A previous purchase is still being finalized. '
                'Please tap Restore Purchases, then try again.'
            : 'Purchase timed out',
      )),
    );
  }

  Future<PurchaseStatusResult> restorePurchases({
    String? userId,
    String? authToken,
  }) async {
    _userId = userId ?? _userId;
    _authToken = authToken ?? _authToken;
    await initialize();
    if (!_ready) {
      return PurchaseStatusResult(
        productId: 'restore',
        status: PaymentStatus.error,
        error: 'In-App Purchase is unavailable on this device',
      );
    }
    await _purchaseEventChain;
    for (final productId in _deferredPurchases.keys.toList()) {
      final recovered = await _retryDeferredPurchase(productId);
      if (recovered != null && recovered.status != PaymentStatus.error) {
        return recovered;
      }
    }
    if (_pending != null && !_pending!.isCompleted) {
      return PurchaseStatusResult(
        productId: 'restore',
        status: PaymentStatus.error,
        error: 'A purchase is already in progress',
      );
    }
    _pendingProductId = 'restore';
    final pending = Completer<PurchaseStatusResult>();
    _pending = pending;
    try {
      await _iap.restorePurchases();
    } catch (e) {
      return _completePending(PurchaseStatusResult(
        productId: 'restore',
        status: PaymentStatus.error,
        error: _safePurchaseError(e),
      ));
    }
    return pending.future.timeout(
      const Duration(seconds: 25),
      onTimeout: () => _completePending(PurchaseStatusResult(
        productId: 'restore',
        status: PaymentStatus.restored,
        restoreData: const {'empty': true},
      )),
    );
  }

  Future<void> _onPurchases(List<PurchaseDetails> purchases) async {
    for (final p in purchases) {
      if (p.status == PurchaseStatus.pending) continue;
      if (p.status == PurchaseStatus.canceled) {
        _failPendingForProduct(p.productID, 'Purchase canceled', canceled: true);
        if (p.pendingCompletePurchase) {
          await _finishPurchase(p);
        }
        continue;
      }
      if (p.status == PurchaseStatus.error) {
        _failPendingForProduct(
            p.productID, p.error?.message ?? 'Purchase failed');
        if (p.pendingCompletePurchase) {
          await _finishPurchase(p);
        }
        continue;
      }
      if (p.status == PurchaseStatus.purchased ||
          p.status == PurchaseStatus.restored) {
        final verified = await _verifyApple(p);
        if (verified && p.pendingCompletePurchase) {
          await _finishPurchase(p);
        }
        if (verified) {
          _deferredPurchases.remove(p.productID);
          _completePendingForProduct(
              p.productID,
              PurchaseStatusResult(
            productId: p.productID,
            status: p.status == PurchaseStatus.restored
                ? PaymentStatus.restored
                : PaymentStatus.purchased,
          ));
        } else {
          // Finish failed subscription transactions so StoreKit cannot strand
          // the product in a duplicate-purchase state. Active subscriptions
          // remain recoverable through Restore Purchases. Consumables stay
          // deferred until their entitlement can be safely credited.
          if (PaymentService.subscriptionIds.contains(p.productID) &&
              p.pendingCompletePurchase) {
            await _finishPurchase(p);
          } else {
            _deferredPurchases[p.productID] = p;
          }
          _failPendingForProduct(
            p.productID,
            'Your purchase is pending verification. It has not been lost. '
            'Please tap Restore Purchases to finish activation.',
          );
        }
      }
    }
  }

  Future<PurchaseStatusResult?> _retryDeferredPurchase(String productId) async {
    final purchase = _deferredPurchases[productId];
    if (purchase == null) return null;
    final verified = await _verifyApple(purchase);
    if (!verified) {
      return PurchaseStatusResult(
        productId: productId,
        status: PaymentStatus.error,
        error: 'Your previous purchase is still pending verification. '
            'Please tap Restore Purchases to finish activation.',
      );
    }
    if (purchase.pendingCompletePurchase) {
      await _finishPurchase(purchase);
    }
    _deferredPurchases.remove(productId);
    return PurchaseStatusResult(
      productId: productId,
      status: purchase.status == PurchaseStatus.restored
          ? PaymentStatus.restored
          : PaymentStatus.purchased,
    );
  }

  Future<void> _finishPurchase(PurchaseDetails purchase) async {
    try {
      await _iap.completePurchase(purchase);
    } catch (e, st) {
      _logger.e('IapService: completePurchase failed for ${purchase.productID}',
          error: e, stackTrace: st);
      rethrow;
    }
  }

  bool _isDuplicateTransactionError(Object error) =>
      error.toString().contains('storekit_duplicate_product_object') ||
      error.toString().contains('pending transaction for the same product');

  String _safePurchaseError(Object error) {
    if (_isDuplicateTransactionError(error)) {
      return 'A previous purchase is still being finalized. '
          'Please tap Restore Purchases, then try again.';
    }
    return 'The App Store could not complete this purchase. Please try again.';
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

  void _completePendingForProduct(
      String productId, PurchaseStatusResult result) {
    if (_pendingProductId == 'restore' || _pendingProductId == productId) {
      _completePending(result);
    }
  }

  void _failPending(String message, {bool canceled = false}) {
    _completePending(PurchaseStatusResult(
      productId: _pendingProductId ?? '',
      status: canceled ? PaymentStatus.canceled : PaymentStatus.error,
      error: message,
    ));
  }

  void _failPendingForProduct(String productId, String message,
      {bool canceled = false}) {
    if (_pendingProductId == 'restore' || _pendingProductId == productId) {
      _failPending(message, canceled: canceled);
    }
  }
}
