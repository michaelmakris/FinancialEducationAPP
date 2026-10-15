"""
What Tsimp (the mosquito coach) says: short lessons, page notes and daily tips, in
Greek and English. Plain education about the practice portfolio -- never a
recommendation to buy or sell anything. services/coach.py decides WHEN to say it.

Lessons answer the buttons under a pop-up instantly (no AI call); "ask" is the
question the chat is opened with if the customer wants to go further.
"""
from __future__ import annotations

LANGS = ("el", "en")

LESSONS: dict[str, dict] = {
    "concentration": {
        "el": {"title": "Όλα τα αυγά σε ένα καλάθι",
               "text": "Όταν μεγάλο μέρος των χρημάτων σου είναι σε μία μόνο επένδυση, το αποτέλεσμά σου εξαρτάται σχεδόν "
                       "ολόκληρο από αυτήν. Αν πέσει 30%, ένα χαρτοφυλάκιο που έχει τα 70% εκεί χάνει περίπου 21%. "
                       "Γι' αυτό πολλοί επενδυτές βάζουν ένα όριο, π.χ. όχι πάνω από 10–20% σε μία μετοχή.",
               "ask": "Πόσο θα έχανε το χαρτοφυλάκιό μου αν η μεγαλύτερη θέση μου έπεφτε 30%;"},
        "en": {"title": "All your eggs in one basket",
               "text": "When a large part of your money sits in one investment, your result depends almost entirely on it. "
                       "If it falls 30%, a portfolio with 70% there loses about 21%. That is why many investors set a limit, "
                       "for example no more than 10–20% in one share.",
               "ask": "How much would my portfolio lose if my largest holding fell 30%?"},
        "next": ["diversification", "volatility"],
    },
    "diversification": {
        "el": {"title": "Τι είναι η διαφοροποίηση;",
               "text": "Διαφοροποίηση σημαίνει να μοιράζεις τα χρήματα σε επενδύσεις που δεν κινούνται όλες μαζί: "
                       "διαφορετικές εταιρείες, κλάδους, χώρες και κατηγορίες (μετοχές, ομόλογα, μετρητά). Όταν μία πέφτει, "
                       "κάποια άλλη μπορεί να κρατάει. Δεν εξαφανίζει το ρίσκο, αλλά μειώνει την εξάρτηση από ένα αποτέλεσμα.",
               "ask": "Πόσο διαφοροποιημένο είναι το χαρτοφυλάκιό μου;"},
        "en": {"title": "What is diversification?",
               "text": "Diversification means spreading money across investments that do not all move together: different "
                       "companies, sectors, countries and asset types (shares, bonds, cash). When one falls, another may hold up. "
                       "It does not remove risk, but it reduces how much one outcome can hurt you.",
               "ask": "How diversified is my portfolio?"},
        "next": ["etf", "concentration"],
    },
    "volatility": {
        "el": {"title": "Τι μετράει η μεταβλητότητα;",
               "text": "Η μεταβλητότητα δείχνει πόσο έντονα ανεβοκατεβαίνει μια τιμή, όχι προς τα πού θα πάει. "
                       "Μεταβλητότητα 30% τον χρόνο σημαίνει ότι διακυμάνσεις της τάξης του ±30% μέσα σε ένα έτος είναι συνηθισμένες. "
                       "Όσο μεγαλύτερη, τόσο πιο ανώμαλη η διαδρομή.",
               "ask": "Ποια από τις θέσεις μου έχει τη μεγαλύτερη μεταβλητότητα;"},
        "en": {"title": "What does volatility measure?",
               "text": "Volatility shows how sharply a price swings, not which way it will go. A volatility of 30% a year means "
                       "moves of around ±30% within a year are common. The higher it is, the bumpier the ride.",
               "ask": "Which of my holdings is the most volatile?"},
        "next": ["drawdown", "time_horizon"],
    },
    "crypto_risk": {
        "el": {"title": "Γιατί τα κρυπτονομίσματα είναι πιο ριψοκίνδυνα",
               "text": "Τα κρυπτονομίσματα κινούνται πολύ πιο έντονα από τις μετοχές: πτώσεις 50–80% έχουν συμβεί αρκετές φορές. "
                       "Δεν έχουν κέρδη ή μερίσματα για να στηρίξουν την τιμή, οπότε κινούνται κυρίως με τη διάθεση της αγοράς. "
                       "Για έναν προσεκτικό επενδυτή συνήθως είναι μικρό κομμάτι, αν υπάρχουν καθόλου.",
               "ask": "Πόσο μεγάλη ήταν η χειρότερη πτώση του Bitcoin;"},
        "en": {"title": "Why crypto is riskier",
               "text": "Crypto moves far more sharply than shares: falls of 50–80% have happened several times. There are no "
                       "profits or dividends behind the price, so it moves mostly with market mood. For a cautious investor it is "
                       "usually a small slice, if any.",
               "ask": "How big was Bitcoin's worst fall?"},
        "next": ["risk_profile", "volatility"],
    },
    "fomo": {
        "el": {"title": "Αγορά μετά από μεγάλη άνοδο",
               "text": "Όταν κάτι έχει ανέβει πολύ, είναι φυσικό να θέλεις να μπεις πριν «χάσεις» τη συνέχεια (FOMO). "
                       "Η προηγούμενη άνοδος όμως δεν λέει τι θα γίνει μετά· μερικές φορές ακολουθεί διόρθωση. "
                       "Μια ερώτηση που βοηθάει: θα το αγόραζα και αν δεν είχε ανέβει;",
               "ask": "Πώς κινήθηκε αυτή η επένδυση τον τελευταίο χρόνο;"},
        "en": {"title": "Buying after a big jump",
               "text": "When something has risen a lot, it is natural to want in before you 'miss' the rest (FOMO). "
                       "But the past rise says nothing about what comes next; sometimes a pullback follows. "
                       "A helpful question: would I buy it if it had not just gone up?",
               "ask": "How has this investment moved over the last year?"},
        "next": ["volatility", "time_horizon"],
    },
    "loss_selling": {
        "el": {"title": "Πουλάω με ζημιά;",
               "text": "Μια ζημιά «στα χαρτιά» γίνεται πραγματική όταν πουλήσεις. Αυτό μπορεί να είναι λογικό αν άλλαξε ο λόγος "
                       "που αγόρασες, αλλά συχνά πουλάμε από φόβο μετά από πτώση και χάνουμε την ανάκαμψη. "
                       "Ρώτα τον εαυτό σου: πουλάω επειδή άλλαξε κάτι ή επειδή φοβάμαι;",
               "ask": "Τι είναι η πραγματοποιημένη και τι η μη πραγματοποιημένη ζημιά;"},
        "en": {"title": "Selling at a loss?",
               "text": "A loss 'on paper' becomes real when you sell. That can be sensible if your reason for buying has changed, "
                       "but often we sell out of fear after a fall and miss the recovery. Ask yourself: am I selling because "
                       "something changed, or because I am scared?",
               "ask": "What is the difference between a realised and an unrealised loss?"},
        "next": ["realised_unrealised", "market_moves"],
    },
    "market_moves": {
        "el": {"title": "Οι μέρες με μεγάλες κινήσεις είναι φυσιολογικές",
               "text": "Οι τιμές ανεβοκατεβαίνουν κάθε μέρα. Μια μετοχή μπορεί να κινηθεί ±5% σε μια μέρα χωρίς κάτι δραματικό. "
                       "Αυτό που μετράει για έναν μακροπρόθεσμο επενδυτή είναι η πορεία σε χρόνια, όχι σε ώρες. "
                       "Κοιτάζοντας κάθε λεπτό, το ρίσκο μοιάζει μεγαλύτερο απ' ό,τι είναι.",
               "ask": "Πόσο συχνά πέφτει μια μετοχή πάνω από 5% σε μία μέρα;"},
        "en": {"title": "Big daily moves are normal",
               "text": "Prices move up and down every day. A share can move ±5% in a day without anything dramatic happening. "
                       "What matters to a long-term investor is the path over years, not hours. Checking every minute makes "
                       "risk feel bigger than it is.",
               "ask": "How often does a share fall more than 5% in a day?"},
        "next": ["time_horizon", "drawdown"],
    },
    "cash_role": {
        "el": {"title": "Ο ρόλος των μετρητών",
               "text": "Τα μετρητά δεν κερδίζουν πολύ, αλλά δεν πέφτουν όταν πέφτει η αγορά και σου δίνουν επιλογές. "
                       "Πολύ λίγα μετρητά σημαίνει ότι δεν μπορείς να αντιδράσεις· πάρα πολλά σημαίνει ότι ο πληθωρισμός τρώει την αξία τους. "
                       "Το σωστό μείγμα εξαρτάται από το προφίλ ρίσκου σου.",
               "ask": "Πόσα μετρητά προτείνει το εκπαιδευτικό πλάνο για το προφίλ μου;"},
        "en": {"title": "The role of cash",
               "text": "Cash earns little, but it does not fall when markets fall and it gives you options. Too little cash means "
                       "you cannot react; too much means inflation slowly eats its value. The right mix depends on your risk profile.",
               "ask": "How much cash does the learning plan suggest for my profile?"},
        "next": ["risk_profile", "diversification"],
    },
    "currency_risk": {
        "el": {"title": "Ο κίνδυνος νομίσματος",
               "text": "Οι αμερικανικές μετοχές τιμολογούνται σε δολάρια. Η αξία τους σε ευρώ αλλάζει και με την ισοτιμία: "
                       "αν το δολάριο πέσει 10% έναντι του ευρώ, χάνεις περίπου 10% ακόμη κι αν η μετοχή μείνει ίδια. "
                       "Αυτό μπορεί να δουλέψει και υπέρ σου.",
               "ask": "Πόσο επηρεάζει η ισοτιμία ευρώ/δολαρίου τις θέσεις μου;"},
        "en": {"title": "Currency risk",
               "text": "US shares are priced in dollars. Their value in euros also moves with the exchange rate: if the dollar falls "
                       "10% against the euro, you lose about 10% even if the share stays flat. It can work in your favour too.",
               "ask": "How much does the euro/dollar rate affect my holdings?"},
        "next": ["diversification"],
    },
    "risk_profile": {
        "el": {"title": "Τι είναι το προφίλ ρίσκου;",
               "text": "Το προφίλ ρίσκου (1 έως 7) δείχνει πόσες διακυμάνσεις μπορείς να αντέξεις, για πόσο καιρό επενδύεις και "
                       "τι σε ενοχλεί πιο πολύ. Το βρίσκεις με 8 ερωτήσεις στο «My plan» και καθορίζει το εκπαιδευτικό μείγμα "
                       "που σου δείχνουμε.",
               "ask": "Τι σημαίνει το προφίλ ρίσκου μου για το χαρτοφυλάκιό μου;"},
        "en": {"title": "What is a risk profile?",
               "text": "Your risk profile (1 to 7) reflects how much ups and downs you can live with, how long you invest for and "
                       "what worries you most. You find it with 8 questions in 'My plan', and it sets the learning mix we show you.",
               "ask": "What does my risk profile mean for my portfolio?"},
        "next": ["cash_role", "time_horizon"],
    },
    "realised_unrealised": {
        "el": {"title": "Πραγματοποιημένο ή όχι;",
               "text": "Μη πραγματοποιημένο κέρδος ή ζημιά είναι η διαφορά ανάμεσα στην τιμή αγοράς και τη σημερινή τιμή όσο κρατάς "
                       "τη θέση. Γίνεται πραγματοποιημένο όταν πουλήσεις. Στη σελίδα Portfolio βλέπεις και τα δύο ξεχωριστά.",
               "ask": "Πόσο είναι το πραγματοποιημένο και πόσο το μη πραγματοποιημένο αποτέλεσμά μου;"},
        "en": {"title": "Realised or not?",
               "text": "An unrealised gain or loss is the difference between what you paid and today's price while you still hold. "
                       "It becomes realised when you sell. The Portfolio page shows both separately.",
               "ask": "What are my realised and unrealised results?"},
        "next": ["loss_selling"],
    },
    "etf": {
        "el": {"title": "Τι είναι ένα ETF;",
               "text": "Ένα ETF είναι ένα «καλάθι» με πολλές επενδύσεις που αγοράζεις σαν μία μετοχή. Ένα ETF στον MSCI World, "
                       "για παράδειγμα, περιέχει πάνω από 1.000 εταιρείες από πολλές χώρες. Είναι ένας απλός τρόπος για διαφοροποίηση "
                       "με λίγα χρήματα.",
               "ask": "Ποια ETF υπάρχουν στην εφαρμογή;"},
        "en": {"title": "What is an ETF?",
               "text": "An ETF is a basket of many investments that you buy like a single share. An MSCI World ETF, for example, "
                       "holds more than 1,000 companies from many countries. It is a simple way to diversify with little money.",
               "ask": "Which ETFs are in the app?"},
        "next": ["index", "diversification"],
    },
    "index": {
        "el": {"title": "Τι είναι ένας δείκτης;",
               "text": "Ένας δείκτης (π.χ. Γενικός Δείκτης Αθηνών, S&P 500) μετράει πώς κινείται μια ομάδα μετοχών μαζί. "
                       "Δεν αγοράζεται απευθείας, αλλά χρησιμεύει ως μέτρο σύγκρισης: πήγε η μετοχή μου καλύτερα ή χειρότερα από την αγορά;",
               "ask": "Πώς πήγε ο Γενικός Δείκτης Αθηνών φέτος;"},
        "en": {"title": "What is an index?",
               "text": "An index (e.g. the Athens General, the S&P 500) measures how a group of shares moves together. "
                       "You cannot buy it directly, but it is a yardstick: did my share do better or worse than the market?",
               "ask": "How has the Athens General index done this year?"},
        "next": ["etf"],
    },
    "pe_ratio": {
        "el": {"title": "Τι είναι ο δείκτης P/E;",
               "text": "Ο δείκτης P/E διαιρεί την τιμή της μετοχής με τα κέρδη ανά μετοχή. P/E 15 σημαίνει ότι πληρώνεις 15 ευρώ για κάθε "
                       "1 ευρώ ετήσιου κέρδους. Υψηλό P/E συχνά σημαίνει ότι η αγορά περιμένει ανάπτυξη· έχει νόημα κυρίως σε σύγκριση "
                       "με παρόμοιες εταιρείες.",
               "ask": "Ποιες ελληνικές εταιρείες έχουν οικονομικά στοιχεία στην εφαρμογή;"},
        "en": {"title": "What is a P/E ratio?",
               "text": "The P/E ratio divides the share price by earnings per share. A P/E of 15 means you pay 15 euros for every "
                       "1 euro of yearly profit. A high P/E often means the market expects growth; it is most useful compared with similar companies.",
               "ask": "Which Greek companies have financials in the app?"},
        "next": ["index"],
    },
    "luck_vs_skill": {
        "el": {"title": "Καλή μέρα: τύχη ή ικανότητα;",
               "text": "Μια μέρα με κέρδη είναι ευχάριστη, αλλά σε μικρά διαστήματα το αποτέλεσμα είναι κυρίως τύχη. "
                       "Το να αυξάνεις το ρίσκο επειδή πήγε καλά μια μέρα είναι συνηθισμένη παγίδα (υπερβολική αυτοπεποίθηση). "
                       "Κρίνε μια στρατηγική σε χρόνια, όχι σε μέρες.",
               "ask": "Πώς πήγε το χαρτοφυλάκιό μου από την αρχή;"},
        "en": {"title": "A good day: luck or skill?",
               "text": "A day of gains feels good, but over short periods results are mostly luck. Taking more risk because one day "
                       "went well is a common trap (overconfidence). Judge a strategy over years, not days.",
               "ask": "How has my portfolio done since I started?"},
        "next": ["time_horizon"],
    },
    "compounding": {
        "el": {"title": "Η δύναμη του ανατοκισμού",
               "text": "Ανατοκισμός σημαίνει ότι τα κέρδη σου αρχίζουν να βγάζουν κι αυτά κέρδη. Με 5% τον χρόνο, 1.000 ευρώ γίνονται "
                       "περίπου 1.630 σε 10 χρόνια και 2.650 σε 20. Γι' αυτό ο χρόνος συχνά μετράει περισσότερο από το πότε ακριβώς μπαίνεις.",
               "ask": "Τι κάνει ο Simulator της εφαρμογής;"},
        "en": {"title": "The power of compounding",
               "text": "Compounding means your gains start earning gains of their own. At 5% a year, 1,000 euros becomes about 1,630 "
                       "in 10 years and 2,650 in 20. That is why time often matters more than exactly when you start.",
               "ask": "What does the app's Simulator do?"},
        "next": ["time_horizon"],
    },
    "delayed_prices": {
        "el": {"title": "Γιατί οι τιμές είναι καθυστερημένες",
               "text": "Οι τιμές μετοχών εδώ έρχονται από δωρεάν πηγές με καθυστέρηση περίπου 15 λεπτών (τα κρυπτονομίσματα είναι ζωντανά). "
                       "Για εκπαίδευση αρκεί· για πραγματικές συναλλαγές θα χρειαζόσουν τιμές σε πραγματικό χρόνο από τον χρηματιστή σου.",
               "ask": "Πότε ανοίγει και κλείνει το Χρηματιστήριο Αθηνών;"},
        "en": {"title": "Why prices are delayed",
               "text": "Share prices here come from free sources with about a 15-minute delay (crypto is live). That is fine for "
                       "learning; for real trades you would need real-time prices from your broker.",
               "ask": "When does the Athens exchange open and close?"},
        "next": ["market_moves"],
    },
    "time_horizon": {
        "el": {"title": "Ο χρονικός ορίζοντας",
               "text": "Ο χρονικός ορίζοντας είναι πόσο καιρό σκοπεύεις να μείνουν επενδυμένα τα χρήματα. Σε 1 χρόνο οι μετοχές μπορεί "
                       "να είναι αρκετά κάτω· σε 10 χρόνια οι διακυμάνσεις έχουν συνήθως εξομαλυνθεί. Χρήματα που θα χρειαστείς σύντομα "
                       "συνήθως δεν μπαίνουν σε ριψοκίνδυνες επενδύσεις.",
               "ask": "Πώς επηρεάζει ο ορίζοντας το προφίλ ρίσκου μου;"},
        "en": {"title": "Your time horizon",
               "text": "Your time horizon is how long you plan to keep the money invested. Over 1 year shares can be well down; over "
                       "10 years the swings have usually evened out. Money you will need soon usually does not go into risky investments.",
               "ask": "How does my horizon affect my risk profile?"},
        "next": ["risk_profile", "compounding"],
    },
    "drawdown": {
        "el": {"title": "Τι είναι το drawdown;",
               "text": "Drawdown είναι η πτώση από το υψηλότερο σημείο μέχρι το χαμηλότερο που ακολούθησε. Ένα drawdown -40% σημαίνει "
                       "ότι κάποιος που αγόρασε στην κορυφή είδε την επένδυση να χάνει 40% πριν (ίσως) ανακάμψει. "
                       "Είναι ένα καλό τεστ: θα άντεχα να το δω αυτό χωρίς να πουλήσω;",
               "ask": "Ποιο ήταν το μεγαλύτερο drawdown του Γενικού Δείκτη Αθηνών;"},
        "en": {"title": "What is a drawdown?",
               "text": "A drawdown is the fall from a peak to the lowest point that followed. A drawdown of -40% means someone who "
                       "bought at the top saw the investment lose 40% before it (maybe) recovered. It is a good test: could I watch "
                       "that without selling?",
               "ask": "What was the Athens General index's biggest drawdown?"},
        "next": ["volatility", "time_horizon"],
    },
}

LESSONS.update({
    "transaction_costs": {
        "el": {"title": "Τι κοστίζει στην πραγματικότητα μια συναλλαγή",
               "text": "Κάθε αγορά και πώληση έχει κόστος: προμήθεια χρηματιστή (συχνά με ελάχιστη χρέωση), τέλη χρηματιστηρίου, "
                       "το spread ανάμεσα σε τιμή αγοράς και πώλησης και, για ξένες μετοχές, μετατροπή νομίσματος. Σε μια μικρή αγορά "
                       "η ελάχιστη προμήθεια μπορεί να είναι αρκετά τοις εκατό· όσο πιο συχνά αγοράζεις και πουλάς, τόσο περισσότερο "
                       "τρώνε τα κόστη από την απόδοση.",
               "ask": "Πόσα έχω πληρώσει σε κόστη συναλλαγών μέχρι τώρα;"},
        "en": {"title": "What a trade really costs",
               "text": "Every buy and sell has a cost: the broker's commission (often with a minimum), exchange fees, the spread "
                       "between the buying and selling price and, for foreign shares, currency conversion. On a small trade the minimum "
                       "commission can be several percent; the more often you buy and sell, the more costs eat into your return.",
               "ask": "How much have I paid in transaction costs so far?"},
        "next": ["compounding", "time_horizon"],
    },
    "fixed_vs_variable": {
        "el": {"title": "Σταθερό ή κυμαινόμενο επιτόκιο;",
               "text": "Με σταθερό επιτόκιο η δόση μένει ίδια για τη συμφωνημένη περίοδο: ξέρεις τι θα πληρώνεις. Με κυμαινόμενο "
                       "πληρώνεις Euribor + το περιθώριο της τράπεζας, οπότε η δόση ακολουθεί το Euribor. Από το 2022 στο 2023 το Euribor "
                       "ανέβηκε από κάτω από το μηδέν σε σχεδόν 4%, και πολλές κυμαινόμενες δόσεις ανέβηκαν απότομα.",
               "ask": "Πόσο θα άλλαζε η δόση ενός στεγαστικού αν το Euribor ανέβει 2 μονάδες;"},
        "en": {"title": "Fixed or variable rate?",
               "text": "With a fixed rate the payment stays the same for the agreed period: you know what you'll pay. With a variable "
                       "rate you pay Euribor + the bank's margin, so the payment follows Euribor. Between 2022 and 2023 Euribor went from "
                       "below zero to almost 4%, and many variable payments rose sharply.",
               "ask": "How much would a mortgage payment change if Euribor rose 2 points?"},
        "next": ["time_horizon", "cash_role"],
    },
})

# First visit to a page: one short note about what is on the screen.
PAGE_NOTES: dict[str, dict] = {
    "discover": {"lesson": "index",
                 "el": "Εδώ βλέπεις πραγματικές μετοχές, ETF και κρυπτονομίσματα ανά αγορά. Οι στήλες 1D, 1M, 1Y δείχνουν πώς άλλαξε η τιμή σε μία μέρα, έναν μήνα και έναν χρόνο.",
                 "en": "Here you see real shares, ETFs and crypto by market. The 1D, 1M and 1Y columns show how the price changed over a day, a month and a year."},
    "asset": {"lesson": "volatility",
              "el": "Το γράφημα «Today» δείχνει την τιμή μέσα στη μέρα· η διακεκομμένη γραμμή είναι το χθεσινό κλείσιμο. Πάνω από αυτήν: η τιμή ανέβηκε σήμερα.",
              "en": "The 'Today' chart shows the price through the day; the dashed line is yesterday's close. Above it: the price is up today."},
    "portfolio": {"lesson": "realised_unrealised",
                  "el": "Αυτό είναι το εκπαιδευτικό σου χαρτοφυλάκιο με εικονικά 10.000 €. Το «Today» δείχνει την αξία του μέσα στη μέρα και το «Realised» ό,τι κέρδισες ή έχασες από πωλήσεις.",
                  "en": "This is your practice portfolio with a virtual EUR 10,000. 'Today' shows its value through the day and 'Realised' what you gained or lost from sales."},
    "plan": {"lesson": "risk_profile",
             "el": "Με 8 ερωτήσεις βρίσκουμε το προφίλ ρίσκου σου και σου δείχνουμε ένα εκπαιδευτικό μείγμα επενδύσεων με stress tests.",
             "en": "With 8 questions we find your risk profile and show you a learning mix of investments with stress tests."},
    "compare": {"lesson": "volatility",
                "el": "Η σύγκριση δείχνει απόδοση και ρίσκο δίπλα-δίπλα. Μεγαλύτερη απόδοση συχνά έρχεται με μεγαλύτερες διακυμάνσεις.",
                "en": "Compare shows return and risk side by side. Higher returns often come with bigger swings."},
    "simulator": {"lesson": "compounding",
                  "el": "Ο Simulator δοκιμάζει χιλιάδες πιθανές πορείες για ένα μείγμα επενδύσεων. Δείχνει εύρος αποτελεσμάτων, όχι πρόβλεψη.",
                  "en": "The Simulator tries thousands of possible paths for a mix of investments. It shows a range of outcomes, not a forecast."},
    "loans": {"lesson": "fixed_vs_variable",
              "el": "Εδώ βλέπεις πόσο κοστίζει ένα δάνειο: δόση, συνολικοί τόκοι και τι γίνεται με κυμαινόμενο επιτόκιο αν αλλάξει το Euribor. Τα σημερινά επιτόκια είναι πραγματικά.",
              "en": "Here you see what a loan costs: the payment, total interest, and what happens to a variable rate if Euribor moves. Today's rates are real."},
    "home": {"lesson": "diversification",
             "el": "Γεια! Είμαι ο Τσιμπ. Θα σε τσιμπάω πού και πού με μια σκέψη για τις επενδυτικές σου αποφάσεις. Μπορείς να με ρωτάς ό,τι θες ή να με κλείσεις από τις ρυθμίσεις.",
             "en": "Hi! I'm Tsimp. Now and then I'll bite with a thought about your investing decisions. Ask me anything, or switch me off in the settings."},
}

# One short tip a day (picked by date).
DAILY_TIPS = [
    ("diversification", "Μια καλή συνήθεια: καμία μεμονωμένη επένδυση πάνω από το 20% του χαρτοφυλακίου.",
     "A good habit: no single investment above 20% of the portfolio."),
    ("time_horizon", "Χρήματα που θα χρειαστείς τα επόμενα 2 χρόνια συνήθως δεν μπαίνουν σε μετοχές.",
     "Money you will need in the next 2 years usually stays out of shares."),
    ("market_moves", "Το να κοιτάς το χαρτοφυλάκιο κάθε ώρα κάνει τις διακυμάνσεις να μοιάζουν μεγαλύτερες.",
     "Checking your portfolio every hour makes the swings feel bigger."),
    ("etf", "Ένα ETF μπορεί να σου δώσει εκατοντάδες εταιρείες με μία αγορά.",
     "One ETF can give you hundreds of companies in a single buy."),
    ("compounding", "Με 5% τον χρόνο, τα χρήματα διπλασιάζονται σε περίπου 14 χρόνια.",
     "At 5% a year, money doubles in about 14 years."),
    ("crypto_risk", "Τα κρυπτονομίσματα έχουν πέσει πάνω από 70% αρκετές φορές μέσα στα τελευταία 10 χρόνια.",
     "Crypto has fallen more than 70% several times in the last 10 years."),
    ("fomo", "Πριν αγοράσεις κάτι που «όλοι» αγοράζουν, ρώτα: γιατί το θέλω εγώ;",
     "Before buying what 'everyone' is buying, ask: why do I want it?"),
    ("currency_risk", "Οι αμερικανικές μετοχές έχουν δύο κινήσεις για σένα: της μετοχής και του δολαρίου.",
     "US shares move twice for you: the share and the dollar."),
    ("cash_role", "Λίγα μετρητά στην άκρη σού επιτρέπουν να αντιδράσεις χωρίς να πουλήσεις σε κακή στιγμή.",
     "A little cash aside lets you react without selling at a bad moment."),
    ("drawdown", "Ρώτα τον εαυτό σου: αν το χαρτοφυλάκιό μου έπεφτε 30%, τι θα έκανα;",
     "Ask yourself: if my portfolio fell 30%, what would I do?"),
    ("pe_ratio", "Ένας δείκτης P/E έχει νόημα κυρίως σε σύγκριση με παρόμοιες εταιρείες του ίδιου κλάδου.",
     "A P/E ratio means most when compared with similar companies in the same sector."),
    ("luck_vs_skill", "Μια καλή εβδομάδα δεν αποδεικνύει μια καλή στρατηγική.",
     "One good week does not prove a good strategy."),
    ("transaction_costs", "Μια αγορά 100 € με ελάχιστη προμήθεια 8 € ξεκινά ήδη 8% κάτω.",
     "A EUR 100 buy with an EUR 8 minimum commission starts 8% down."),
    ("fixed_vs_variable", "Σε δάνειο με κυμαινόμενο επιτόκιο, ρώτα: θα άντεχα τη δόση αν το Euribor ανέβαινε 2 μονάδες;",
     "On a variable-rate loan, ask: could I still pay if Euribor rose 2 points?"),
]


def lesson(lesson_id: str, lang: str) -> dict | None:
    item = LESSONS.get(lesson_id)
    if item is None:
        return None
    lang = lang if lang in LANGS else "en"
    return {"id": lesson_id, **item[lang],
            "next": [{"id": n, "title": LESSONS[n][lang]["title"]} for n in item.get("next", []) if n in LESSONS]}
