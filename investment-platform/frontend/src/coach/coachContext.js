import { createContext, useContext } from "react";

// Tsimp, the mosquito coach: shared state for pop-ups and the chat (CoachProvider.jsx).
export const CoachContext = createContext(null);

export function useCoach() {
  return useContext(CoachContext);
}

// UI words around the coach's messages (the messages themselves come from the API).
export const UI = {
  el: {
    name: "Τσιμπ", role: "ο εκπαιδευτικός σου βοηθός", continue: "Συνέχεια με την αγορά", continueSell: "Συνέχεια με την πώληση",
    cancel: "Ακύρωση", dismiss: "Κλείσιμο", portfolio: "Εκπαιδευτικό χαρτοφυλάκιο", chosen: "Επιλεγμένη επένδυση",
    ofAvailable: (p) => `${p} του διαθέσιμου ποσού σε μία επένδυση`, decision: "Επενδυτική απόφαση",
    placeholder: "Ρώτα με ό,τι θες...", askMore: "Ρώτα κάτι παραπάνω", thinking: "σκέφτομαι",
    popups: "Αναδυόμενα μηνύματα", on: "Ναι", off: "Όχι", openPage: "Άνοιγμα", more: "ακόμη",
    hello: "Γεια! Είμαι ο Τσιμπ 🦟. Ρώτα με για μια μετοχή, το χαρτοφυλάκιό σου ή μια έννοια, π.χ. «τι είναι η διαφοροποίηση;» ή «αγόρασε 5 ETE.AT».",
    error: "Δεν μπόρεσα να απαντήσω τώρα. Δοκίμασε ξανά σε λίγο.",
  },
  en: {
    name: "Tsimp", role: "your learning buddy", continue: "Continue with the buy", continueSell: "Continue with the sale",
    cancel: "Cancel", dismiss: "Dismiss", portfolio: "Practice portfolio", chosen: "Chosen investment",
    ofAvailable: (p) => `${p} of the available amount in one investment`, decision: "Investment decision",
    placeholder: "Ask me anything...", askMore: "Ask a follow-up", thinking: "thinking",
    popups: "Pop-up messages", on: "On", off: "Off", openPage: "Open", more: "more",
    hello: "Hi! I'm Tsimp 🦟. Ask me about a share, your portfolio or an idea, e.g. \"what is diversification?\" or \"buy 5 ETE.AT\".",
    error: "I couldn't answer just now. Try again in a moment.",
  },
};
