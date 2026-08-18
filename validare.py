"""
Functii de validare pentru date specifice (CNP romanesc, IBAN).
"""

from datetime import date

# Constanta oficiala folosita la calculul cifrei de control a CNP-ului.
CONSTANTA_CONTROL_CNP = "279146358279"

# Coduri de judet valide (01-46 judete + 51-52 Bucuresti sectoare + 47 nerezidenti
# sunt tratate generic ca interval 01-52, conform cerintei).
JUDET_MIN = 1
JUDET_MAX = 52

# Zile din fiecare luna (indice 1-12); februarie tratata cu 29 pentru a nu
# respinge anii bisecti (validarea stricta a bisectilor nu e ceruta).
ZILE_LUNA = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def valideaza_cnp(cnp: str) -> tuple[bool, str]:
    """
    Valideaza structura si cifra de control a unui CNP romanesc.
    Returneaza (True, "") daca e valid, altfel (False, motiv_eroare).
    """
    if not cnp or not isinstance(cnp, str):
        return False, "CNP-ul este obligatoriu"

    if len(cnp) != 13 or not cnp.isdigit():
        return False, "CNP-ul trebuie sa contina exact 13 cifre"

    prima_cifra = int(cnp[0])
    if prima_cifra < 1 or prima_cifra > 9:
        return False, "Prima cifra a CNP-ului este invalida"

    luna = int(cnp[3:5])
    if luna < 1 or luna > 12:
        return False, "Luna nasterii din CNP este invalida"

    zi = int(cnp[5:7])
    if zi < 1 or zi > ZILE_LUNA[luna]:
        return False, "Ziua nasterii din CNP este invalida"

    judet = int(cnp[7:9])
    if judet < JUDET_MIN or judet > JUDET_MAX:
        return False, "Codul de judet din CNP este invalid"

    cifra_control_calculata = _calculeaza_cifra_control(cnp)
    cifra_control_primita = int(cnp[12])
    if cifra_control_calculata != cifra_control_primita:
        return False, "Cifra de control a CNP-ului este invalida"

    return True, ""


def _calculeaza_cifra_control(cnp: str) -> int:
    """Calculeaza cifra de control conform algoritmului oficial (MOD 11)."""
    suma = sum(int(cnp[i]) * int(CONSTANTA_CONTROL_CNP[i]) for i in range(12))
    rest = suma % 11
    return 0 if rest == 10 else rest


def extrage_data_nasterii(cnp: str) -> date:
    """
    Determina data completa a nasterii dintr-un CNP valid, tinand cont de secol
    (prima cifra: 1/2 -> 1900, 3/4 -> 1800, 5/6 -> 2000).
    """
    prima_cifra = int(cnp[0])
    an_scurt = int(cnp[1:3])
    luna = int(cnp[3:5])
    zi = int(cnp[5:7])

    if prima_cifra in (1, 2):
        secol = 1900
    elif prima_cifra in (3, 4):
        secol = 1800
    elif prima_cifra in (5, 6):
        secol = 2000
    else:
        # 7/8/9 = rezidenti straini; presupunem secolul curent ca fallback rezonabil.
        secol = 2000

    return date(secol + an_scurt, luna, zi)


def extrage_gen(cnp: str) -> str:
    """Determina genul din CNP: cifre impare (1,3,5,7,9) = M, cifre pare (2,4,6,8) = F."""
    prima_cifra = int(cnp[0])
    return "M" if prima_cifra % 2 == 1 else "F"


def genereaza_cnp_test(
    an: int, luna: int, zi: int, judet: int = 1, gen: str = "M", secventa: int = 1
) -> str:
    """
    Genereaza un CNP valid structural, pentru scopuri de testare.
    Nu corespunde niciunei persoane reale - secventa e aleasa manual de apelant.
    """
    if secol_din_an_gen(an, gen) is None:
        raise ValueError("Combinatie an/gen neacoperita de generatorul de test")

    prima_cifra = secol_din_an_gen(an, gen)
    an_scurt = an % 100

    cnp_fara_control = (
        f"{prima_cifra}"
        f"{an_scurt:02d}"
        f"{luna:02d}"
        f"{zi:02d}"
        f"{judet:02d}"
        f"{secventa:03d}"
    )

    cifra_control = _calculeaza_cifra_control(cnp_fara_control + "0")
    return cnp_fara_control + str(cifra_control)


def secol_din_an_gen(an: int, gen: str) -> int | None:
    """Helper: determina prima cifra a CNP-ului in functie de an si gen (M/F)."""
    gen = gen.upper()
    if 1900 <= an <= 1999:
        return 1 if gen == "M" else 2
    if 1800 <= an <= 1899:
        return 3 if gen == "M" else 4
    if 2000 <= an <= 2099:
        return 5 if gen == "M" else 6
    return None


def valideaza_iban(iban: str) -> bool:
    """
    Valideaza un IBAN folosind algoritmul standard MOD 97.
    Utilitar general, nu este folosit in fluxul de autentificare.
    """
    if not iban or not isinstance(iban, str):
        return False

    iban_curat = iban.replace(" ", "").upper()

    if len(iban_curat) < 15 or len(iban_curat) > 34:
        return False

    if not iban_curat.isalnum():
        return False

    # Muta primele 4 caractere la finalul sirului.
    iban_rearanjat = iban_curat[4:] + iban_curat[:4]

    # Converteste literele in numere: A=10, B=11, ..., Z=35.
    iban_numeric = "".join(
        str(int(caracter, 36)) if caracter.isalpha() else caracter
        for caracter in iban_rearanjat
    )

    return int(iban_numeric) % 97 == 1
