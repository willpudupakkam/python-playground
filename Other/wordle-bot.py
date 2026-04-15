import random
import matplotlib.pyplot as plt

# --- Load and normalize the word list (strip blanks, dedupe, keep 5-letter words only) ---
with open('./words.txt', 'r') as myfile:
    wordlist = [w.strip().lower() for w in myfile.read().split('\n') if w.strip()]
    # If the list contains non-5-letter words, filtering them helps pruning
    wordlist = [w for w in dict.fromkeys(wordlist) if len(w) == 5]

# --- Fast single-game simulation (no globals, iterative, uses candidate filtering) ---
def play_one_game(words) -> int:
    secret_word = random.choice(words)

    # Knowledge learned so far
    learned = [''] * 5            # fixed-position letters as we learn them
    exists = set()                # letters that exist somewhere in the word
    not_exists = set()            # letters known to not exist in the word
    already = set()               # guesses we've already tried

    # Maintain a shrinking candidate list so we don't scan the entire list every guess
    candidates = words[:]

    guesses = 0

    def ok(w: str) -> bool:
        # Fast rejects using set logic
        if w in already:
            return False
        letters = set(w)
        if letters & not_exists:
            return False
        # All known existing letters must appear
        if not exists.issubset(letters):
            return False
        # Respect positional constraints
        for i, ch in enumerate(w):
            if learned[i] and ch != learned[i]:
                return False
        return True

    while True:
        # Pick a guess from the current candidate set
        # (random choice to avoid adversarial first item patterns)
        guess = random.choice(candidates) if candidates else random.choice(words)
        already.add(guess)
        guesses += 1

        if guess == secret_word:
            return guesses

        # Learn from feedback (green/yellow/gray semantics)
        for i, ch in enumerate(guess):
            if ch == secret_word[i]:
                learned[i] = ch
                exists.add(ch)
            elif ch in secret_word:
                exists.add(ch)
            else:
                not_exists.add(ch)

        # Shrink candidate list using what we learned this round
        candidates = [w for w in candidates if ok(w)]
        if not candidates:
            # Fallback: re-filter from the full dictionary if we exhausted candidates
            candidates = [w for w in words if ok(w)]
            if not candidates:  # Secret word not in list (shouldn't happen if list is consistent)
                # Make a random guess to avoid an infinite loop and finish the game
                candidates = [random.choice(words)]

# --- Run many trials and build a histogram of guess counts ---
def run_trials(num_trials: int = 10_000):
    data = {}
    for _ in range(num_trials):
        g = play_one_game(wordlist)
        data[g] = data.get(g, 0) + 1
    return dict(sorted(data.items()))


def plot_hist_from_counts(counts, xlabel="Guesses", ylabel="Games", title="Wordle Bot Performance"):
    xs = sorted(counts.keys())
    ys = [counts[k] for k in xs]

    plt.figure()
    plt.bar(xs, ys, width=0.8, align="center")
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.title(title)
    plt.xticks(xs)
    plt.tight_layout()
    plt.show()


if __name__ == '__main__':
    results = run_trials(10_000)
    plot_hist_from_counts(results)