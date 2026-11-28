# Vylepšení slepého detektiva: výsledky (2026-11-28)

Zadání: `reports/Prompt vylepšení detektiva.md`. Podrobnosti a zdůvodnění každého pravidla jsou v
`DECISIONS.md`, rozhodnutí 133–138. Nic není commitnuté.

**Sada.** Example A (40k zákazníků, medium) seedy 42, 7, 1, 2, 3, 4 a Example B (30k, hard) seedy 42, 7, 1,
každý s no-story dvojčetem. Výstup scanu bez LLM, scorer `s2d/score.py` beze změny. F1 je strict
(TP / všechna hlášení). Údaj „dvojče“ = falešné nálezy na jeden běh dvojčete (670 dní ≈ 1,8 roku; rozpočet
1 za rok ≈ 1,8 na běh).

## Výsledek

| | TP z 5 | falešné / běh | F1 | F1 s důsledky | dvojče / běh |
|---|---|---|---|---|---|
| před | 1,56 | 5,89 | 0,214 | 0,255 | 3,67 |
| po | **2,22** | **3,89** | **0,360** | **0,394** | **2,33** |
| jen A | 1,67 → 2,33 | 4,5 → 3,2 | 0,24 → 0,40 | | 4,5 → 2,7 |
| jen B | 1,33 → 2,00 | 8,7 → 5,3 | 0,15 → 0,27 | | 2,0 → 1,7 |

Výchozí stav na této sadě je horší než 0,435 ze zprávy (A 0,24, B 0,15). Běh detektivu samotného:
21 s (A) a 16 s (B), před změnami 17 s a 12 s.

## Krok 0: oracle-located z (výchozí kód) a finální stav

Oracle z = DiD a placebo z detektivu na správné řadě, ke správnému datu (start + lag, okno „po“ za rampou).
E3 (výpadek dodavatele) se páruje přes vyprodání, oracle pro něj nemá smysl.

| běh | událost | d (ověřovatel) | oracle z | z detektivu | nalezeno | proč ne | finální stav |
|---|---|---|---|---|---|---|---|
| A_s42 | E1 price_change | 3.8 | 2.9 | – | ano |  | nalezeno |
| A_s42 | E2 price_change | 4.63 | 3.2 | 3.4 | ne | práh / datování (z detektivu 3.43) | nalezeno |
| A_s42 | E3 supplier_del | 13.98 | – | – | ano |  | nalezeno |
| A_s42 | E4 quality_issu | 5.9 | 13.0 | 3.0 | ne | práh / datování (z detektivu 2.96) | ne |
| A_s42 | E5 competitor_e | 2.38 | 3.9 | – | ne | netestováno (brána / žádný zlom) | ne |
| A_s7 | E1 price_change | 2.02 | 2.6 | – | ne | netestováno (brána / žádný zlom) | ne |
| A_s7 | E2 price_change | 6.4 | 6.2 | 6.0 | ano |  | nalezeno |
| A_s7 | E3 supplier_del | 14.64 | – | – | ano |  | nalezeno |
| A_s7 | E4 quality_issu | 4.88 | 5.9 | 5.9 | ano |  | nalezeno |
| A_s7 | E5 competitor_e | 3.54 | 5.6 | – | ne | netestováno (brána / žádný zlom) | ne |
| A_s1 | E1 price_change | 2.47 | 2.3 | – | ne | netestováno (brána / žádný zlom) | ne |
| A_s1 | E2 price_change | 2.91 | 6.2 | 3.3 | ne | práh / datování (z detektivu 3.33) | ne |
| A_s1 | E3 supplier_del | 10.9 | – | – | ano |  | nalezeno |
| A_s1 | E4 quality_issu | 8.03 | 5.8 | 6.9 | ne | pravidlo: sloučeno (merge) | ne |
| A_s1 | E5 competitor_e | 3.21 | 3.5 | – | ne | netestováno (brána / žádný zlom) | ne |
| A_s2 | E1 price_change | 3.12 | 3.0 | – | ne | netestováno (brána / žádný zlom) | ne |
| A_s2 | E2 price_change | 4.63 | 5.8 | 7.7 | ne | datování | ne |
| A_s2 | E3 supplier_del | 15.02 | – | – | ano |  | nalezeno |
| A_s2 | E4 quality_issu | 7.8 | 8.1 | 7.8 | ne | pravidlo: sloučeno (merge) | nalezeno |
| A_s2 | E5 competitor_e | 4.79 | 7.5 | – | ne | netestováno (brána / žádný zlom) | nalezeno |
| A_s3 | E1 price_change | 3.34 | 3.4 | – | ano |  | nalezeno |
| A_s3 | E2 price_change | 7.46 | 6.8 | 3.6 | ne | práh / datování (z detektivu 3.58) | nalezeno |
| A_s3 | E3 supplier_del | 14.24 | – | – | ano |  | nalezeno |
| A_s3 | E4 quality_issu | 4.49 | 7.2 | 12.1 | ne | pravidlo: sloučeno (merge) | ne |
| A_s3 | E5 competitor_e | 4.37 | 5.9 | – | ne | netestováno (brána / žádný zlom) | ne |
| A_s4 | E1 price_change | 3.04 | 2.8 | – | ne | netestováno (brána / žádný zlom) | ne |
| A_s4 | E2 price_change | 4.5 | 3.2 | 4.4 | ne | práh / datování (z detektivu 4.41) | ne |
| A_s4 | E3 supplier_del | 16.61 | – | – | ano |  | nalezeno |
| A_s4 | E4 quality_issu | 5.34 | 3.9 | 4.0 | ne | práh / datování (z detektivu 4.05) | ne |
| A_s4 | E5 competitor_e | 5.36 | 6.3 | – | ne | netestováno (brána / žádný zlom) | ne |

Co z toho plyne (a proč se pořadí změn lišilo od zprávy):
- E2 a E4 mají sílu (oracle z ≥ 5,7 ve 4 z 6 a ≥ 5,8 v 5 z 6 seedů). Chyběl správný datum a `merge`
  slučoval churn různých segmentů do jedné události, takže E4 spolkl nesouvisející nález.
- E5 má sílu ve 4 z 6 seedů (oracle 5,5–7,5), ale nebyl testován vůbec: brána přes rodiče.
- E1 je opravdu slabý (ověřovatel z 2,0–3,3): informační limit, ne práh.
- Snížení prahu (miss c) nic nepřineslo: k = 1,6 nepřidalo žádný TP, jen falešné nálezy.

## Změny jedna po druhé (kumulativně, 9 story běhů + 9 dvojčat)

| krok | TP | falešné | F1 | F1 s důsl. | dvojče | ponecháno |
|---|---|---|---|---|---|---|
| výchozí | 1,56 | 5,89 | 0,214 | 0,255 | 3,67 | |
| oprava `merge` (segmenty se musí překrývat) | 1,78 | 6,89 | 0,216 | 0,272 | 3,78 | ano (oprava chyby) |
| 1. ukotvená rodina + churn proti nové frekvenci | 2,00 | 7,00 | 0,232 | 0,297 | 3,78 | ano |
| 2. poměrové KPI ze sečtených počtů s φ | 2,11 | 5,56 | 0,260 | 0,331 | 3,78 | ano |
| 3. vyprodání, substituce, čisté kontroly | 2,11 | 4,22 | 0,345 | 0,372 | 2,33 | ano |
| 4. max-T práh po úrovních (k = 1,85) | 2,11 | 3,89 | 0,345 | 0,378 | 2,33 | ano |
| 4'. totéž s k = 1,6 | 2,11 | 5,00 | 0,315 | 0,347 | 4,11 | ne |
| 5'. všechny páry bez brány | 2,22 | 4,56 | 0,345 | 0,375 | 3,44 | ne |
| 5. jen buňky město × kanál bez brány | **2,22** | **3,89** | **0,360** | **0,394** | **2,33** | ano |

Ablace finálního stavu: bez ukotvené rodiny F1 0,265 (TP 1,67); bez sečtených poměrů F1 0,307
(6,2 falešných na běh). Dvojčata se při tom nemění (2,33 a 2,44): kotvy na dvojčatech nejsou.

## Co bylo jinak, než navrhovalo zadání

- **Max-T (změna 4):** horní kvantil maxim přes placebo data na story běhu měří samotný příběh
  (90. percentil 19,3 proti 4,6 na dvojčeti) a step-down se zhroutí k z ≈ 2. Stabilní je medián
  maxim (story a dvojče se liší o < 0,15), takže práh = 1,85 × medián, počítaný na každém datasetu.
- **Ukotvená rodina:** zpoždění 14/28/42 dávala datum až o 7 dní vedle a scorer (τ = 7) za to nedá nic.
  Proto denní zpoždění 0–56 a datum na vrcholu z, zprůměrovaného přes 3 týdny. Placebo data vynechávají
  i 168 dní po kotvě, protože tam efekt může končit (s kratší mezerou vycházelo p = 0,3 i pro z = 7).
- **Churn proti nové frekvenci:** krok frekvence segmentu se hledá jen u cenových kotev (z tabulky cen),
  ne na výstupní KPI. Varianta „poslední 3 mezery zákazníka“ byla smíšená a nepoužívá se.
- **Cenový test objednávek** zůstává z ≥ 3 (rozhodnutí 131). Jeho empirické placebo p je u E1 0,12–0,17,
  takže už teď běží zhruba na α 0,1 a kalibrované p by E1 ztratilo.
- **Změna 5** jen pro objednávky město × kanál. Všechny páry přidaly falešné nálezy (nové zákazníky,
  repeat rate, kategorie) bez dalšího TP.

## Jak daleko je stopka

Stopka splněná není:
- dvojčata mají 2,33 na běh (cíl ≤ 2); 14 z 21 jsou spiky (6 z nich decoy), na ty se zatím nesahalo;
- zmeškané události bez kotvy s oracle z ≥ 4: E5 ve 3 seedech (oracle 5,6–6,3) a E4 ve 3 seedech (5,8–13),
  vždy kvůli datování nebo chybějícímu zlomu, ne kvůli prahu.

Další krok je tedy datování (E4: kandidát z úrovně „všichni“ s horším datem vyhrává merge na z) a pravidlo
pro krátké spiky, ne další ladění prahů. Odhad zprávy (strop 0,68–0,74) zatím zůstává daleko.

Skripty měření (scratchpad, smažou se po restartu): `evalrun.py`, `diag.py`, `churn_exp.py`, `maxt.py`,
`dating.py` v `/tmp/claude-1000/-home-mekysjos-hackathon-27-12-2026/730be792-2121-4414-8b6b-89a7f2c124ab/scratchpad/`.
