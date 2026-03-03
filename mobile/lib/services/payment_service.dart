// =============================================================================
// LITTLE NATE — Payment Service
// Platform-aware payment abstraction: StoreKit (iOS), Google Play (Android),
// Stripe (web). Server-side receipt verification for native IAP.
// =============================================================================

import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:http/http.dart' as http;
import 'package:logger/logger.dart';
import 'package:url_launcher/url_launcher.dart';

import '../config/app_config.dart';

// Only import in_app_purchase on native platforms to avoid web build issues
import 'package:in_app_purchase/in_app_purchase.dart';

/// Platform-aware payment abstraction that routes:
/// - iOS: StoreKit via in_app_purchase
/// - Android: Google Play Billing via in_app_purchase
/// - Web: Stripe Checkout (redirect)
class PaymentService {
  PaymentService._();
  static final PaymentService _instance = PaymentService._();
  static PaymentService get instance => _instance;

  final _logger = Logger();
  final _purchaseUpdates = StreamController<PurchaseStatusResult>.broadcast();

  /// Stream of purchase status updates (pending, purchased, error, canceled).
  Stream<PurchaseStatusResult> get purchaseUpdates => _purchaseUpdates.stream;

  InAppPurchase? _iap;
  StreamSubscription<List<PurchaseDetails>>? _subscription;
  String? _userId;
  String? _authToken;

  // Product IDs — must match App Store Connect / Play Console exactly
  // Subscriptions (auto-renewable)
  static const innerChamberMonthly = 'net.sovereignsanctuary.inner_chamber_monthly';
  static const innerChamberAnnual = 'net.sovereignsanctuary.inner_chamber_annual';
  static const sovereignCircleMonthly = 'net.sovereignsanctuary.sovereign_circle_monthly';
  static const sovereignCircleBiannual = 'net.sovereignsanctuary.sovereign_circle_annual'; // $749/6mo

  // Token packs (consumable)
  static const tokenLight = 'net.sovereignsanctuary.token_light3';       // 15,000 tokens — $2.99
  static const tokenStandard = 'net.sovereignsanctuary.token_standard7'; // 50,000 tokens — $7.00
  static const tokenPower = 'net.sovereignsanctuary.token_power';        // 150,000 tokens — $20.00
  static const tokenUltimate = 'net.sovereignsanctuary.token_ultimate';  // 1,000,000 tokens — $125.00

  static const Set<String> subscriptionIds = {
    innerChamberMonthly,
    innerChamberAnnual,
    sovereignCircleMonthly,
    sovereignCircleBiannual,
  };

  static const Set<String> tokenPackIds = {
    tokenLight,
    tokenStandard,
    tokenPower,
    tokenUltimate,
  };

  static const Set<String> productIds = {
    ...subscriptionIds,
    ...tokenPackIds,
  };

  /// Auth context required for server-side receipt verification and web checkout.
  /// Call when user logs in.
  void setAuthContext(String userId, String? authToken) {
    _userId = userId;
    _authToken = authToken;
  }

  /// Initialize IAP listeners and load products (native only). On web, no-op.
  Future<void> initialize() async {
    if (kIsWeb) {
      _logger.i('PaymentService: Web platform — using Stripe for purchases');
      return;
    }

    try {
      _iap = InAppPurchase.instance;
      final available = await _iap!.isAvailable();
      if (!available) {
        _logger.w('PaymentService: IAP not available on this device');
        return;
      }

      _subscription = _iap!.purchaseStream.listen(
        _handlePurchaseUpdate,
        onDone: () => _subscription?.cancel(),
        onError: (e) => _logger.e('PaymentService: Purchase stream error', error: e),
      );

      final response = await _iap!.queryProductDetails(productIds);
      if (response.notFoundIDs.isNotEmpty) {
        _logger.w('PaymentService: Products not found in store: ${response.notFoundIDs}');
      }
      if (response.productDetails.isEmpty) {
        _logger.w('PaymentService: No products loaded from store');
      }
    } catch (e, st) {
      _logger.e('PaymentService: Initialize failed', error: e, stackTrace: st);
    }
  }

  /// Initiate purchase. On native: IAP flow. On web: redirect to Stripe Checkout.
  Future<void> purchase(String productId, {String? userId, String? authToken}) async {
    final uid = userId ?? _userId;
    final token = authToken ?? _authToken;

    if (kIsWeb) {
      await _purchaseViaStripe(productId, uid: uid, token: token);
      return;
    }

    if (!productIds.contains(productId)) {
      _logger.e('PaymentService: Unknown product $productId');
      _purchaseUpdates.add(PurchaseStatusResult(
        productId: productId,
        status: PaymentStatus.error,
        error: 'Unknown product ID',
      ));
      return;
    }

    try {
      final response = await _iap!.queryProductDetails({productId});
      final product = response.productDetails.firstWhere(
        (p) => p.id == productId,
        orElse: () => throw StateError('Product $productId not found'),
      );

      final purchaseParam = PurchaseParam(productDetails: product);
      if (tokenPackIds.contains(product.id)) {
        await _iap!.buyConsumable(purchaseParam: purchaseParam);
      } else {
        await _iap!.buyNonConsumable(purchaseParam: purchaseParam);
      }
    } catch (e, st) {
      _logger.e('PaymentService: Purchase failed for $productId', error: e, stackTrace: st);
      _purchaseUpdates.add(PurchaseStatusResult(
        productId: productId,
        status: PaymentStatus.error,
        error: e.toString(),
      ));
    }
  }

  /// Restore previous purchases. On native: IAP restore. On web: fetch subscription from backend.
  Future<void> restorePurchases({String? authToken}) async {
    if (kIsWeb) {
      await _restoreFromBackend(token: authToken ?? _authToken);
      return;
    }

    try {
      await _iap?.restorePurchases();
    } catch (e, st) {
      _logger.e('PaymentService: Restore failed', error: e, stackTrace: st);
      _purchaseUpdates.add(PurchaseStatusResult(
        productId: '',
        status: PaymentStatus.error,
        error: e.toString(),
      ));
    }
  }

  /// Clean up streams and subscriptions.
  void dispose() {
    _subscription?.cancel();
    _purchaseUpdates.close();
  }

  void _handlePurchaseUpdate(List<PurchaseDetails> purchases) {
    for (final purchase in purchases) {
      switch (purchase.status) {
        case PurchaseStatus.pending:
          _purchaseUpdates.add(PurchaseStatusResult(
            productId: purchase.productID,
            status: PaymentStatus.pending,
          ));
          break;
        case PurchaseStatus.purchased:
        case PurchaseStatus.restored:
          _verifyReceipt(purchase);
          if (purchase.pendingCompletePurchase) {
            _iap?.completePurchase(purchase);
          }
          _purchaseUpdates.add(PurchaseStatusResult(
            productId: purchase.productID,
            status: purchase.status == PurchaseStatus.purchased
                ? PaymentStatus.purchased
                : PaymentStatus.restored,
          ));
          break;
        case PurchaseStatus.error:
          _purchaseUpdates.add(PurchaseStatusResult(
            productId: purchase.productID,
            status: PaymentStatus.error,
            error: purchase.error?.message ?? 'Unknown error',
          ));
          break;
        case PurchaseStatus.canceled:
          _purchaseUpdates.add(PurchaseStatusResult(
            productId: purchase.productID,
            status: PaymentStatus.canceled,
          ));
          break;
      }
    }
  }

  Future<void> _verifyReceipt(PurchaseDetails purchase) async {
    final uid = _userId;
    if (uid == null || uid.isEmpty) {
      _logger.w('PaymentService: No user ID — skipping server verification');
      return;
    }

    final token = _authToken;
    final headers = <String, String>{
      'Content-Type': 'application/json',
      if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
    };

    final baseUrl = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'));
    final base = '$baseUrl/api/billing';

    try {
      if (purchase.verificationData.source == 'App Store') {
        final receiptData = purchase.verificationData.serverVerificationData;
        final body = jsonEncode({
          'receipt_data': receiptData,
          'user_id': uid,
          'product_id': purchase.productID,
        });
        final resp = await http.post(
          Uri.parse('$base/verify-receipt/apple'),
          headers: headers,
          body: body,
        );
        if (resp.statusCode >= 200 && resp.statusCode < 300) {
          _logger.i('PaymentService: Apple receipt verified for ${purchase.productID}');
        } else {
          _logger.w('PaymentService: Apple receipt verify failed: ${resp.statusCode} ${resp.body}');
        }
      } else if (purchase.verificationData.source == 'Google Play') {
        final purchaseToken = purchase.verificationData.serverVerificationData;
        final body = jsonEncode({
          'purchase_token': purchaseToken,
          'product_id': purchase.productID,
          'user_id': uid,
          'package_name': 'net.sovereignsanctuary.littlenate',
        });
        final resp = await http.post(
          Uri.parse('$base/verify-receipt/google'),
          headers: headers,
          body: body,
        );
        if (resp.statusCode >= 200 && resp.statusCode < 300) {
          _logger.i('PaymentService: Google receipt verified for ${purchase.productID}');
        } else {
          _logger.w('PaymentService: Google receipt verify failed: ${resp.statusCode} ${resp.body}');
        }
      }
    } catch (e, st) {
      _logger.e('PaymentService: Receipt verification failed', error: e, stackTrace: st);
    }
  }

  Future<void> _purchaseViaStripe(String productId, {String? uid, String? token}) async {
    if (uid == null || token == null || token.isEmpty) {
      _logger.e('PaymentService: Web checkout requires auth context');
      _purchaseUpdates.add(PurchaseStatusResult(
        productId: productId,
        status: PaymentStatus.error,
        error: 'Not authenticated',
      ));
      return;
    }

    const successUrl = 'https://app.sovereignsanctuary.net/billing/success';
    const cancelUrl = 'https://app.sovereignsanctuary.net/billing/cancel';

    final baseUrl = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'));

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
          Uri.parse('$baseUrl/api/billing/token-pack/checkout'),
          headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer $token',
          },
          body: jsonEncode({
            'pack': packName,
            'success_url': successUrl,
            'cancel_url': cancelUrl,
          }),
        );
        if (resp.statusCode >= 200 && resp.statusCode < 300) {
          final data = jsonDecode(resp.body) as Map<String, dynamic>;
          final url = data['checkout_url'] as String?;
          if (url != null && url.isNotEmpty) {
            final launched = await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
            if (!launched) {
              _logger.w('PaymentService: Could not launch Stripe checkout URL');
              _purchaseUpdates.add(PurchaseStatusResult(
                productId: productId,
                status: PaymentStatus.error,
                error: 'Could not open checkout',
              ));
            }
          }
        } else {
          _logger.w('PaymentService: Token pack checkout failed: ${resp.statusCode} ${resp.body}');
          _purchaseUpdates.add(PurchaseStatusResult(
            productId: productId,
            status: PaymentStatus.error,
            error: 'Checkout failed: ${resp.statusCode}',
          ));
        }
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
          }),
        );
        if (resp.statusCode >= 200 && resp.statusCode < 300) {
          final data = jsonDecode(resp.body) as Map<String, dynamic>;
          final url = data['checkout_url'] as String?;
          if (url != null && url.isNotEmpty) {
            final launched = await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
            if (!launched) {
              _logger.w('PaymentService: Could not launch Stripe checkout URL');
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
    } catch (e, st) {
      _logger.e('PaymentService: Stripe checkout failed', error: e, stackTrace: st);
      _purchaseUpdates.add(PurchaseStatusResult(
        productId: productId,
        status: PaymentStatus.error,
        error: e.toString(),
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
      _logger.w('PaymentService: Restore on web requires auth token');
      return;
    }

    final baseUrl = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'));

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

/// Platform-agnostic purchase status.
enum PaymentStatus { pending, purchased, restored, error, canceled }

/// Result of a purchase status update, used by the purchase stream.
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
