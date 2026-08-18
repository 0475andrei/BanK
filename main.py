"""
Punct de intrare simplu (CLI) pentru testarea manuala a modulului de autentificare.
Nu contine date sensibile - parola introdusa nu e niciodata afisata sau logata.
"""

import getpass

from auth import inregistreaza_user, logare


def meniu_inregistrare() -> None:
    print("\n--- Inregistrare cont nou ---")
    email = input("Email: ").strip()
    parola = getpass.getpass("Parola: ")
    nume = input("Nume: ").strip()
    prenume = input("Prenume: ").strip()
    cnp = input("CNP: ").strip()
    telefon = input("Telefon (optional): ").strip() or None
    adresa = input("Adresa (optional): ").strip() or None

    rezultat = inregistreaza_user(
        email=email,
        parola=parola,
        nume=nume,
        prenume=prenume,
        cnp=cnp,
        telefon=telefon,
        adresa=adresa,
    )

    if rezultat["success"]:
        print(rezultat["mesaj"])
    else:
        print(f"Eroare: {rezultat['error']}")


def meniu_logare() -> None:
    print("\n--- Logare ---")
    email = input("Email: ").strip()
    parola = getpass.getpass("Parola: ")

    rezultat = logare(email, parola)
    if rezultat["success"]:
        user = rezultat["user"]
        print(f"Bine ai venit, {user['prenume']} {user['nume']}!")
    else:
        print(f"Eroare: {rezultat['error']}")


def main() -> None:
    optiuni = {
        "1": meniu_inregistrare,
        "2": meniu_logare,
    }

    while True:
        print("\n=== Aplicatie bancara demo - Autentificare ===")
        print("1. Inregistrare cont nou")
        print("2. Logare")
        print("0. Iesire")

        alegere = input("Alege o optiune: ").strip()
        if alegere == "0":
            break

        actiune = optiuni.get(alegere)
        if actiune is None:
            print("Optiune invalida.")
            continue

        actiune()


if __name__ == "__main__":
    main()
