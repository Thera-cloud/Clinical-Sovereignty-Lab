using Sovereign.ClinicalEngine;
using Sovereign.Shared.Contracts;

namespace Sovereign.Client;

public class MainDashboard
{
    private readonly SessionProcessor _processor = new();

    public void OnClick_ProcessSession(ISessionContract session)
    {
        Console.WriteLine("🖥️  UI: User clicked 'Process Session'...");
        
        try 
        {
            // The UI hands the data to the Engine for verification
            _processor.ProcessClinicalSession(session);
            Console.WriteLine("✅ UI: Session processed successfully.");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"⚠️ UI ALERT: {ex.Message}");
        }
    }
}