namespace Sovereign.Shared.Contracts;

public interface ISessionContract
{
    double ResonanceScore { get; set; }
    bool IsEncrypted { get; }
    // I intentionally removed encryption
}
