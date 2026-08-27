import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:logger/logger.dart';

import '../config/app_config.dart';
import 'checkout_launcher.dart';
import 'iap_service.dart';

/// Payments: StoreKit on native iOS, Stripe checkout elsewhere.
class PaymentService {
  PaymentService._();
  static final PaymentService _instance = PaymentService._();
  static PaymentService get instance => _instance;

  final _logger = Logger();
  final _purchaseUpdates = StreamController<PurchaseStatusResult>.broadcast();

  Stream<PurchaseStatusResult> get purchaseUpdates => _purchaseUpdates.stream;

  String? _userId;
  String? _authToken;

  // Product identifiers used for Stripe tier/pack mapping
  static const innerChamberMonthly = 'net.sovereignsanctuary.inner_chamber_monthly';
  static const innerChamberAnnual = 'net.sovereignsanctuary.inner_chamber_annual';
  static const sovereignCircleMonthly = 'net.sovereignsanctuary.sovereign_circle_monthly';
  static const sovereignCircleBiannual = 'net.sovereignsanctuary.sovereign_circle_annual';

  static const tokenLight = 'net.sovereignsanctuary.token_light3';
  static const tokenStandard = 'net.sovereignsanctuary.token_standard7';
  static const tokenPower = 'net.sovereignsanctuary.token_power';
  static const tokenUltimate = 'net.sovereignsanctuary.token_ultimate';

  static const Set<String> subscriptionIds = {
    innerChamberMonthly, innerChamberAnnual,
    sovereignCircleMonthly, sovereignCircleBiannual,
  };

  static const Set<String> tokenPackIds = {
    tokenLight, tokenStandard, tokenPower, tokenUltimate,
  };

  static const Set<String> productIds = {...subscriptionIds, ...tokenPackIds};

  void setAuthContext(String userId, String? authToken) {
    _userId = userId;
    _authToken = authToken;
  }

  Future<void> initialize() async {
    if (IapService.instance.isNativeIOS) {
      await IapService.instance.initialize();
      return;
    }
    _logger.i('PaymentService: Stripe checkout for non-iOS platforms');
  }

  Future<void> purchase(
    String productId, {
    String? userId,
    String? authToken,
    String? promoCode,
  }) async {
    final uid = userId ?? _userId;
    final token = authToken ?? _authToken;
    if (IapService.instance.isNativeIOS) {
      if (uid == null || uid.isEmpty || token == null || token.isEmpty) {
        _purchaseUpdates.add(PurchaseStatusResult(
          productId: productId,
          status: PaymentStatus.error,
          error: 'Not authenticated',
        ));
        return;
      }
      final result = await IapService.instance.purchase(
        productId,
        userId: uid,
        authToken: token,
      );
      _purchaseUpdates.add(result);
      return;
    }
    await _purchaseViaStripe(productId, uid: uid, token: token, promoCode: promoCode);
  }

  Future<void> restorePurchases({String? authToken}) async {
    if (IapService.instance.isNativeIOS) {
      await IapService.instance.restorePurchases(
        userId: _userId,
        authToken: authToken ?? _authToken,
      );
      return;
    }
    await _restoreFromBackend(token: authToken ?? _authToken);
  }

  void dispose() {
    _purchaseUpdates.close();
  }

  Future<void> _purchaseViaStripe(
    String productId, {
    String? uid,
    String? token,
    String? promoCode,
  }) async {
    if (uid == null || token == null || token.isEmpty) {
      _logger.e('PaymentService: Checkout requires auth context');
      _purchaseUpdates.add(PurchaseStatusResult(
        productId: productId,
        status: PaymentStatus.error,
        error: 'Not authenticated',
      ));
      return;
    }

    const successUrl = 'https://app.sovereignsanctuary.net/payment-complete';
    const cancelUrl = 'https://app.sovereignsanctuary.net/payment-cancelled';
    final baseUrl = AppConfig.apiBaseUrl
        .replaceAll(RegExp(r'/api/?$'), '')
        .replaceAll(RegExp(r'/+$'), '');

    try {
      if (tokenPackIds.contains(productId)) {
        final packName = _productIdToTokenPack(productId);
        if (packName == null) {
          _purchaseUpdates.add(PurchaseStatusResult(
            productId: productId,
            status: PaymentStatus.error,
            error: 'Unknown token pack',
          ));
          return;
        }
        final resp = await http.post(
          Uri.parse('$baseUrl/api/billing/token-packs/purchase'),
          headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer $token',
          },
          body: jsonEncode({
            'pack_id': packName,
            'username': uid,
            'success_url': successUrl,
            'cancel_url': cancelUrl,
          }),
        );
        await _handleCheckoutResponse(resp, productId);
      } else {
        final tier = _productIdToTier(productId);
        if (tier == null) {
          _purchaseUpdates.add(PurchaseStatusResult(
            productId: productId,
            status: PaymentStatus.error,
            error: 'Unknown subscription product',
          ));
          return;
        }
        final resp = await http.post(
          Uri.parse('$baseUrl/api/billing/checkout'),
          headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer $token',
          },
          body: jsonEncode({
            'tier': tier,
            'success_url': successUrl,
            'cancel_url': cancelUrl,
            if (promoCode != null && promoCode.trim().isNotEmpty)
              'promo_code': promoCode.trim(),
          }),
        );
        await _handleCheckoutResponse(resp, productId);
      }
    } catch (e, st) {
      _logger.e('PaymentService: Stripe checkout failed', error: e, stackTrace: st);
      _purchaseUpdates.add(PurchaseStatusResult(
        productId: productId,
        status: PaymentStatus.error,
        error: e.toString(),
      ));
    }
  }

  Future<void> _handleCheckoutResponse(http.Response resp, String productId) async {
    if (resp.statusCode >= 200 && resp.statusCode < 300) {
      final data = jsonDecode(resp.body) as Map<String, dynamic>;
      final url = data['checkout_url'] as String?;
      if (url != null && url.isNotEmpty) {
        final launched = await launchCheckoutUrl(url);
        if (!launched) {
          _logger.w('PaymentService: Could not launch checkout URL');
          _purchaseUpdates.add(PurchaseStatusResult(
            productId: productId,
            status: PaymentStatus.error,
            error: 'Could not open checkout',
          ));
        }
      }
    } else {
      _logger.w('PaymentService: Checkout failed: ${resp.statusCode} ${resp.body}');
      _purchaseUpdates.add(PurchaseStatusResult(
        productId: productId,
        status: PaymentStatus.error,
        error: 'Checkout failed: ${resp.statusCode}',
      ));
    }
  }

  String? _productIdToTier(String productId) {
    if (productId.contains('inner_chamber')) return 'STANDARD';
    if (productId.contains('sovereign_circle')) return 'TOP_TIER';
    return null;
  }

  String? _productIdToTokenPack(String productId) {
    const map = {
      tokenLight: 'light',
      tokenStandard: 'standard',
      tokenPower: 'power',
      tokenUltimate: 'ultimate',
    };
    return map[productId];
  }

  Future<void> _restoreFromBackend({String? token}) async {
    if (token == null || token.isEmpty) {
      _logger.w('PaymentService: Restore requires auth token');
      return;
    }

    final baseUrl = AppConfig.apiBaseUrl
        .replaceAll(RegExp(r'/api/?$'), '')
        .replaceAll(RegExp(r'/+$'), '');

    try {
      final resp = await http.post(
        Uri.parse('$baseUrl/api/billing/restore-purchases'),
        headers: {'Authorization': 'Bearer $token'},
      );
      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        _logger.i('PaymentService: Restored — plan=${data['subscription_plan']}');
        _purchaseUpdates.add(PurchaseStatusResult(
          productId: 'restore',
          status: PaymentStatus.restored,
          restoreData: data,
        ));
      }
    } catch (e, st) {
      _logger.e('PaymentService: Restore from backend failed', error: e, stackTrace: st);
    }
  }
}

enum PaymentStatus { pending, purchased, restored, error, canceled }

class PurchaseStatusResult {
  final String productId;
  final PaymentStatus status;
  final String? error;
  final Map<String, dynamic>? restoreData;

  const PurchaseStatusResult({
    required this.productId,
    required this.status,
    this.error,
    this.restoreData,
  });
}
