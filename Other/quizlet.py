import os
import re
import random
import tkinter as tk
from tkinter import messagebox


def load_definitions(filename: str) -> dict[str, str]:
    """
    Load term/definition pairs from the HTML-ish definitions file.

    Expected pattern in file:
        <p><b>term:</b> definition text</p>
    """
    terms: dict[str, str] = {}

    if not os.path.exists(filename):
        raise FileNotFoundError(f"Definitions file not found: {filename}")

    pattern = re.compile(r"<p><b>([^<]+):</b>\s*(.*?)</p>")

    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            match = pattern.search(line)
            if match:
                term = match.group(1).strip()
                definition = match.group(2).strip()
                # Optional: unescape a few HTML entities if they show up
                definition = (
                    definition.replace("&lt;", "<")
                    .replace("&gt;", ">")
                    .replace("&amp;", "&")
                )
                terms[term] = definition

    if not terms:
        raise ValueError("No term/definition pairs were found in the file.")

    return terms


class FlashcardApp:
    def __init__(self, root: tk.Tk, cards: dict[str, str]) -> None:
        self.root = root
        self.root.title("CS 234 Flashcards")

        # Convert dict to list for indexing and shuffle order
        self.cards = list(cards.items())
        random.shuffle(self.cards)

        self.index = 0
        self.show_term = True  # True => show term, False => show definition

        # ----- UI layout -----
        self.root.configure(padx=20, pady=20)

        self.card_frame = tk.Frame(self.root, bd=2, relief=tk.RIDGE, padx=20, pady=20)
        self.card_frame.grid(row=0, column=0, columnspan=3, sticky="nsew")

        self.card_label = tk.Label(
            self.card_frame,
            text="",
            wraplength=500,
            justify="center",
            font=("Helvetica", 16),
        )
        self.card_label.pack(expand=True, fill="both")

        # Info label
        self.info_label = tk.Label(self.root, text="", anchor="center")
        self.info_label.grid(row=1, column=0, columnspan=3, pady=(10, 0))

        # Buttons
        self.prev_button = tk.Button(self.root, text="⟨ Prev", command=self.prev_card)
        self.prev_button.grid(row=2, column=0, padx=5, pady=10, sticky="ew")

        self.flip_button = tk.Button(self.root, text="Flip", command=self.flip_card)
        self.flip_button.grid(row=2, column=1, padx=5, pady=10, sticky="ew")

        self.next_button = tk.Button(self.root, text="Next ⟩", command=self.next_card)
        self.next_button.grid(row=2, column=2, padx=5, pady=10, sticky="ew")

        # Allow resizing
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_columnconfigure(2, weight=1)

        # Start with the first card
        self.update_card_text()

    # ----- Card logic -----
    def update_card_text(self) -> None:
        term, definition = self.cards[self.index]
        text = term if self.show_term else definition
        self.card_label.config(text=text)

        side = "Term" if self.show_term else "Definition"
        self.info_label.config(
            text=f"Card {self.index + 1}/{len(self.cards)} – showing: {side}"
        )

    def flip_card(self) -> None:
        self.show_term = not self.show_term
        self.update_card_text()

    def next_card(self) -> None:
        self.index = (self.index + 1) % len(self.cards)
        self.show_term = True
        self.update_card_text()

    def prev_card(self) -> None:
        self.index = (self.index - 1) % len(self.cards)
        self.show_term = True
        self.update_card_text()


def main() -> None:
    # Assume definitions.txt is in the same directory as this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    definitions_path = os.path.join(script_dir, "definitions.txt")

    try:
        cards = load_definitions(definitions_path)
    except Exception as e:
        # If something goes wrong loading the file, show a dialog instead of crashing
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Error loading definitions", str(e))
        root.destroy()
        return

    root = tk.Tk()
    app = FlashcardApp(root, cards)
    root.mainloop()


if __name__ == "__main__":
    main()