# KierunkiKontrahentow

Mała nakładka „zawsze na wierzchu" dla stanowiska ważenia/pakowania: pamięta, **na jaki kierunek jedzie towar danego kontrahenta**, i podpowiada go po wpisaniu kodu — zamiast sprawdzać to za każdym razem.

Program jest niezależnym, osobnym narzędziem z własną lokalną bazą (SQLite). Nie łączy się z żadnym serwerem, nie modyfikuje ani nie podpina się pod inne programy i nie jest powiązany z żadnym producentem oprogramowania magazynowego.

## Funkcje

- Wpisujesz kod kontrahenta i Enter — widzisz kierunek na **dzisiaj** (zielony box).
- Jeden kontrahent może mieć **różne kierunki na różne dni tygodnia**.
- Ten sam kod może jechać w kilka miejsc tego samego dnia — dostawy rozróżnia **opis** (np. nazwa punktu z faktury); program pokazuje wtedy wszystkie dzisiejsze dostawy.
- Przycisk **„Wypełnij wszystkie dni"** kopiuje kierunek na każdy dzień tygodnia, który go jeszcze nie ma (nic nie nadpisuje).
- Nagłówek „Wysyłka dnia X na Y" — pakujesz dziś, wysyłka jutro.
- **Dzień roboczy zmienia się o 5:00**, nie o północy (towar jest ważony też po północy). Działa także przy zminimalizowanym oknie.
- Zarządzanie bazą: wyszukiwanie, filtr po dniu, edycja, usuwanie, eksport/import CSV, historia operacji.

## Pobieranie i uruchomienie

- **Gotowy program:** zakładka [Releases](../../releases) → `KierunkiKontrahentow.exe` (Windows, nie wymaga Pythona).
- **Z kodu:** Python 3.10+ z tkinter, następnie `python app.py`.

## Dane, kopie zapasowe i aktualizacja

Baza `kierunki.db` leży **obok pliku `.exe`**. Program robi sam raz dziennie kopię w podfolderze `kopie_zapasowe/` (ostatnie 14 dni) oraz dodatkową, nieusuwaną kopię `*_przed_migracja.db` zawsze, gdy nowa wersja musi zmienić strukturę bazy.

**Aktualizacja = podmiana samego pliku `.exe`.** Nie kasuj i nie nadpisuj `kierunki.db` ani `kopie_zapasowe/`. Nowa wersja otwiera istniejącą bazę, zachowuje kierunki i historię, a w razie zmiany struktury wcześniej robi kopię.

## Budowanie `.exe`

```
pip install pyinstaller
przebuduj_exe.bat
```

## Konfiguracja

Godzina zmiany dnia: `GODZINA_ZMIANY_DNIA` w `db.py` (domyślnie 5).

## Licencja

[MIT](LICENSE). Składniki dołączone do pliku `.exe` — patrz [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt).
