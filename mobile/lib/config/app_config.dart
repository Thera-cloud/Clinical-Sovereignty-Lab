/// LITTLE NATE — App Configuration
/// Clinical Sovereignty Lab
/// 
/// All network and feature configuration in one place.
/// Update these values for different environments.

class AppConfig {
  // ===========================================================================
  // NETWORK CONFIGURATION
  // ===========================================================================
  
  /// Local development host (only used when useProduction is false)
  static const String serverHost = 'localhost';
  
  /// Production domain (API / WebSocket gateway)
  static const String productionDomain = 'api.sovereignsanctuary.net';
  
  /// Use production or local
  static const bool useProduction = true; // Set to false for local development only
  
  /// API server port
  static const int apiPort = 8000;
  
  /// WebSocket bridge port
  static const int wsPort = 8765;
  
  /// Admin console port (for deep linking)
  static const int adminPort = 3000;
  
  // ===========================================================================
  // COMPUTED URLs
  // ===========================================================================
  
  /// Base URL for REST API calls
  static String get apiBaseUrl => useProduction 
      ? 'https://$productionDomain'
      : 'http://$serverHost:$apiPort';
  
  /// WebSocket URL for real-time communication
  static String get wsUrl => useProduction
      ? 'wss://$productionDomain/ws'
      : 'ws://$serverHost:$wsPort';
  
  /// Admin console URL
  static String get adminUrl => useProduction
      ? 'https://command.sovereignsanctuary.net'
      : 'http://$serverHost:$adminPort';
  
  // ===========================================================================
  // API ENDPOINTS
  // ===========================================================================
  
  static String get authLogin => '$apiBaseUrl/api/auth/login';
  static String get authRegister => '$apiBaseUrl/api/auth/register';
  static String get authRefresh => '$apiBaseUrl/api/auth/refresh';
  
  static String get userProfile => '$apiBaseUrl/api/users/me';
  static String get userSettings => '$apiBaseUrl/api/users/me/settings';
  
  static String get sessions => '$apiBaseUrl/api/sessions';
  static String session(String id) => '$apiBaseUrl/api/sessions/$id';
  
  static String get subscription => '$apiBaseUrl/api/billing/subscription';
  static String get checkoutCreate => '$apiBaseUrl/api/billing/checkout';
  
  static String get nevedalStatus => '$apiBaseUrl/api/nevedal/status';
  static String nevedalHistory(String userId) => '$apiBaseUrl/api/nevedal/history/$userId';
  
  // ===========================================================================
  // FEATURE FLAGS
  // ===========================================================================
  
  /// Enable Nevedal biometric tracking
  static const bool enableNevedal = true;
  
  /// Enable voice mode
  static const bool enableVoiceMode = true;
  
  /// Enable live coaching features
  static const bool enableCoaching = false;
  
  /// Enable Stripe payments
  static const bool enableStripe = false;
  
  /// Enable crisis detection alerts
  static const bool enableCrisisDetection = true;
  
  /// Enable Sovereign Vault (B8) — storage, uploads, Transfer Crystal
  static const bool ENABLE_SOVEREIGN_VAULT = true;
  
  // ===========================================================================
  // TIMEOUTS & LIMITS
  // ===========================================================================
  
  /// API request timeout in seconds
  static const int apiTimeout = 30;
  
  /// WebSocket reconnect delay in milliseconds
  static const int wsReconnectDelay = 3000;
  
  /// Maximum reconnect attempts
  static const int maxReconnectAttempts = 5;
  
  /// Session inactivity timeout in minutes
  static const int sessionTimeout = 30;
  
  // ===========================================================================
  // APP INFO
  // ===========================================================================
  
  static const String appName = 'Sovereign Sanctuary';
  static const String appVersion = '1.0.0';
  static const String buildNumber = '1';
  
  // ===========================================================================
  // ENVIRONMENT
  // ===========================================================================
  
  static const String environment = 'development';
  static const bool isProduction = environment == 'production';
  static const bool enableDebugLogs = !isProduction;
}


/// Production configuration (uncomment when deploying)
// class AppConfig {
//   static const String serverHost = 'api.littlenate.ai';
//   static const int apiPort = 443;
//   static const int wsPort = 443;
//   
//   static String get apiBaseUrl => 'https://$serverHost';
//   static String get wsUrl => 'wss://$serverHost/ws';
//   
//   static const bool enableStripe = true;
//   static const bool enableCoaching = true;
//   static const String environment = 'production';
//   static const bool isProduction = true;
//   static const bool enableDebugLogs = false;
// }
