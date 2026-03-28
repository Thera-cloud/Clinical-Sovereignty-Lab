/**
 * ODPE L0 Evaluator — JavaScript port of IcositetragonEvaluator
 * 
 * Evaluates 24 L0 faces (8 functions x 3 scopes) using heuristic
 * input signals derived from message analysis.
 * 
 * Returns { signal, confidence, dominant_face, face_scores }
 */

const CANONICAL_FUNCTIONS = [
  "vectorize_retrieval", "noetic_fusion", "metacognition",
  "quantum_self_coherence", "generative_wisdom", "world_coherence",
  "crystal_lake", "emergent"
];

const SCOPE_LEVELS = ["user", "global", "superseded_chain"];

const NOISE_THRESHOLD = 0.15;
const CONSENSUS_DIVERGENCE = 0.25;
const CONSENSUS_ATTENUATION = 0.6;

const CLINICAL_KEYWORDS = [
  "anxiety", "depression", "trauma", "ptsd", "suicidal", "self-harm",
  "abuse", "panic", "grief", "addiction", "disorder", "therapy",
  "diagnosis", "medication", "bipolar", "schizophrenia", "ocd",
  "eating disorder", "dissociation", "flashback"
];

const DEEP_KEYWORDS = [
  "meaning of life", "existential", "consciousness", "identity",
  "purpose", "spiritual", "soul", "death", "afterlife", "philosophy",
  "quantum", "coherence", "sovereignty", "freedom"
];

const FACTUAL_KEYWORDS = [
  "what is", "how to", "define", "explain", "tell me about",
  "when did", "who was", "difference between", "compare", "list"
];

function analyzeMessage(message) {
  const lower = message.toLowerCase();
  const wordCount = message.split(/\s+/).length;
  const hasQuestion = message.includes("?");
  
  let clinicalScore = 0;
  let deepScore = 0;
  let factualScore = 0;
  
  for (const kw of CLINICAL_KEYWORDS) {
    if (lower.includes(kw)) clinicalScore += 0.15;
  }
  for (const kw of DEEP_KEYWORDS) {
    if (lower.includes(kw)) deepScore += 0.12;
  }
  for (const kw of FACTUAL_KEYWORDS) {
    if (lower.includes(kw)) factualScore += 0.2;
  }
  
  clinicalScore = Math.min(clinicalScore, 1.0);
  deepScore = Math.min(deepScore, 1.0);
  factualScore = Math.min(factualScore, 1.0);
  
  const complexity = Math.min(1.0, wordCount / 50);
  const emotionality = clinicalScore * 0.7 + deepScore * 0.3;
  
  return { clinicalScore, deepScore, factualScore, complexity, emotionality, hasQuestion, wordCount };
}

function evaluateL0(message) {
  const analysis = analyzeMessage(message);
  const faceScores = {};
  
  for (const func of CANONICAL_FUNCTIONS) {
    for (const scope of SCOPE_LEVELS) {
      const key = `${func}:${scope}`;
      let score = 0.1;
      
      switch (func) {
        case "vectorize_retrieval":
          score = analysis.factualScore * 0.8 + 0.1;
          break;
        case "noetic_fusion":
          score = analysis.emotionality * 0.7 + analysis.complexity * 0.3;
          break;
        case "metacognition":
          score = analysis.deepScore * 0.6 + analysis.complexity * 0.4;
          break;
        case "quantum_self_coherence":
          score = analysis.clinicalScore * 0.8 + analysis.emotionality * 0.2;
          break;
        case "generative_wisdom":
          score = analysis.deepScore * 0.5 + analysis.factualScore * 0.3 + 0.1;
          break;
        case "world_coherence":
          score = analysis.factualScore * 0.6 + analysis.complexity * 0.3;
          break;
        case "crystal_lake":
          score = analysis.emotionality * 0.5 + analysis.deepScore * 0.3;
          break;
        case "emergent":
          score = (analysis.clinicalScore + analysis.deepScore + analysis.factualScore) / 3;
          break;
      }
      
      if (scope === "user") score *= 1.1;
      else if (scope === "superseded_chain") score *= 0.8;
      
      faceScores[key] = Math.min(1.0, score);
    }
  }
  
  const scores = Object.values(faceScores);
  const maxScore = Math.max(...scores);
  const avgScore = scores.reduce((a, b) => a + b, 0) / scores.length;
  const spread = maxScore - avgScore;
  
  let signal, confidence;
  
  if (maxScore > 0.7 && spread > 0.3) {
    signal = "DEEP_TENSION";
    confidence = maxScore;
  } else if (maxScore > 0.5 && spread > 0.2) {
    signal = "TENSION";
    confidence = maxScore * 0.9;
  } else if (analysis.factualScore > 0.5 && analysis.clinicalScore < 0.2) {
    signal = "LOCKED";
    confidence = Math.min(0.95, analysis.factualScore + 0.2);
  } else if (maxScore > 0.3) {
    signal = "PROMOTED";
    confidence = maxScore * 0.8;
  } else if (maxScore < NOISE_THRESHOLD) {
    signal = "NOISE";
    confidence = 0.1;
  } else {
    signal = "PROVISIONAL";
    confidence = 0.5;
  }
  
  const dominantFace = Object.entries(faceScores)
    .sort((a, b) => b[1] - a[1])[0];
  
  return {
    signal,
    confidence,
    dominant_face: dominantFace ? dominantFace[0] : "",
    face_scores: faceScores,
    analysis
  };
}

export { evaluateL0, analyzeMessage };
