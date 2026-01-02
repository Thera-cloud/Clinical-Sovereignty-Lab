using Sovereign.ClinicalEngine;
using Sovereign.Shared.Contracts;
using System;

namespace Sovereign.Client;

public class MainDashboard
{
    private readonly SessionProcessor _processor = new();

    // Instead of a Name, we generate a Sovereign Patient Hash
    public string GenerateSecurePatientId(string rawId) {
        // Simple mock of a hashing function for the 5-year study
        return "PX-" + Guid.NewGuid().ToString().Substring(0, 8);
    }

    public void StartClinicalSession(string patientInput)
    {
        string secureId = GenerateSecurePatientId(patientInput);
        Console.WriteLine($"🖥️ UI: Starting Session for {secureId}");
        
        // This is where the UI eventually calls the Engine
    }
}