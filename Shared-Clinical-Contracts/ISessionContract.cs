namespace Sovereign.Shared.Contracts;
/// <summary>
/// The Prime Contract for the 5-Year Sovereign Study.
/// Defines the resonance of a single clinical interaction.
/// </summary>
public interface ISessionContract
{
    Guid SessionId { get; }
    DateTime Timestamp { get; }
    // The "Somatic Resonance" score (Central to your theory)
    double ResonanceScore { get; set; }
    // Privacy Shield: Data must be encrypted before leaving the Vault
  
    void LogAuditTrail(string auditMessage);
}

