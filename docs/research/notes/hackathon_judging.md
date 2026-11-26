# Story2Data challenge at the 4FIS Hackathon (FIS VŠE): event facts and what the judges are likely to reward

## Which hackathon hosts the challenge, who proposed it, and the official logistics?

### Takeaway
Story2Data is one of three challenges at the **4FIS Hackathon, 27–28 November 2026, at xPORT VŠE in Prague**. **4FIS** runs it. 4FIS is the student association at FIS VŠE. **FIS VŠE itself set the challenge**, not a company. **The date is November, not December.** The folder name "27-12-2026" is almost certainly a typo for 27.11.2026. Registration is already closed.

### Cited Findings
- Official page title: "4FIS Hackathon | 27.–28. listopadu 2026 | xPORT VŠE". The organizer is "4FIS, studentský spolek při Fakultě informatiky a statistiky VŠE". The page says "Registrace jsou uzavřené … Registrace uzavřeny 24. 11." — [hackathon.4fis.cz](https://hackathon.4fis.cz/)
- There are three challenges. (1) **Nova**: "Předpověz sledovanost v prime time", a forecast of audience share for ages 15–54, including Christmas. Tags: Data science / ML / Python. (2) **"Výzva – FIS VŠE: Story2Data: od příběhu k datům"**. Tags: Data / AI / Simulace. Text: "Dokážeš vytvořit data, ve kterých se skutečně něco děje? Postav generátor, který z popisu firmy a zadaného příběhu vytvoří propojený dataset. Příběh v něm nesmí být jen popiskem, musí jít dohledat v samotných datech." (3) **Česká spořitelna**: "Za hranicemi bankovní aplikace". Tags: Produkt / UX / Prototyp. — [hackathon.4fis.cz](https://hackathon.4fis.cz/)
- The page describes the three challenges as "data o sledovanosti televize, generování realistických dat a budoucnost bankovnictví". — [hackathon.4fis.cz](https://hackathon.4fis.cz/)
- Schedule:
  - **Friday 27 Nov:** 13:00 opening; 14:00 keynote; 14:15 challenge presentations; **15:00 hacking starts**; 18:30 dinner; 22:00 quiet hours, but hacking continues overnight.
  - **Saturday 28 Nov:** 9:00 breakfast; **12:00 submission**; **13:00–15:00 presentations**; 15:00 evaluation; **15:30 results**; 18:00 afterparty.
  - The page notes the schedule may change slightly.
  - — [hackathon.4fis.cz](https://hackathon.4fis.cz/)
- Prizes: "Prize pool pro první místo je 10.000 Kč! Druhé místo 5.000 Kč!" The prize-card template is still empty, so the prizes are probably overall prizes, not per challenge. — [hackathon.4fis.cz](https://hackathon.4fis.cz/). A search snippet described this as "15 000 Kč pro vítězný tým" ([search summary of hackathon.4fis.cz](https://hackathon.4fis.cz/)). That conflicts with the live page, which says 10k for first and 5k for second, 15k in total.
- Team size: "Vyžadujeme minimálně dvoučlenné týmy". Solo registrants may be matched, but this is not guaranteed. — [hackathon.4fis.cz](https://hackathon.4fis.cz/). A search-engine snippet also said organizers expect 60–80 participants and will select by prior experience if oversubscribed. I could not see that text in the current page source.
- Format: teams explore the brief, consult mentors, build a "prototyp nebo konkrétní koncept", and present to a jury. "Prostor tu mají vývoj, data, design i byznysové uvažování. Důležité je propojit různé zkušenosti a přijít s řešením, které dává smysl." — [hackathon.4fis.cz](https://hackathon.4fis.cz/)
- Jury composition: the partnership section asks partners to provide a challenge, a mentor, and "zástupce vaší firmy v závěrečné porotě". This implies a mixed jury of partner representatives and organizers. — [hackathon.4fis.cz](https://hackathon.4fis.cz/)
- Sponsor logos in the page source: `FIS_logo.png`, `nova1.png`, `oneplay2.png`, `006_Proud logo_white…png`. — [hackathon.4fis.cz](https://hackathon.4fis.cz/) (raw HTML)
- 4FIS was founded in 2016 and links statistics and informatics students. Contact: 4fis.vzdelavacky@gmail.com, and 4fis.hackathon@gmail.com for the hackathon. Registration opened 2 Oct 2026. — [4fis.cz/vzdelavacky-akce/hackathon](https://4fis.cz/vzdelavacky-akce/hackathon/); [hackathon.4fis.cz](https://hackathon.4fis.cz/)

### Inferences
- The challenge is proposed by the faculty, so its owner, mentor and judge are most likely FIS academics. The most likely departments are KIZI (data engineering, knowledge discovery) or the statistics or econometrics departments. A partner company is less likely. These judges will care about methodological rigor and teaching value more than commercial pitch.
- The effective build time is about **21 hours**, from Friday 15:00 to Saturday 12:00, not a full 24h.
- Three challenges share about 2 hours of presentations. With 60–80 participants in teams of 2+, that is roughly 15–25 teams, so each team probably gets **about 5–7 minutes including Q&A**. A tight pitch with a live demo of "story → data → the story found again in the data" matters a lot.
- Prizes appear to be overall, so Story2Data teams likely compete against the Nova and ČS teams for the same two prizes. A mixed jury that includes Nova and ČS people must also understand the project quickly. This favors a vivid business story and a visual "proof" moment.
- "Oneplay" is Nova's streaming service (general knowledge, not verified here), so Nova/Oneplay is a single partner group. I could not identify "Proud".

### Gaps
- I found no published judging criteria or rubric for the 4FIS Hackathon 2026.
- I found no published jury names.
- I found no rules on pre-prepared code, open-source libraries, or LLM/cloud API use. Ask the organizers at 4fis.hackathon@gmail.com or at the opening.
- I could not identify which FIS department or person wrote the Story2Data brief. The fuller brief is presumably presented at 14:15 on Friday.
- It is unclear whether prizes are per challenge or overall. The page shows a single pool.

## Official rules and judging criteria, plus proxies from earlier 4FIS events and other Czech hackathons

### Takeaway
4FIS has published no criteria. The best Czech proxy is UP Olomouc's "Když data promluví" data hackathon. It scores 0–10 each on **innovation, quality and correctness of execution, practical usability, sustainability, and presentation**. It requires a solution schema, a demo of outputs, and a SWOT analysis. It explicitly asks teams to **disclose how they used AI**, and it scores only the team's own work. International rubrics converge on technical difficulty, originality, usefulness or impact, and presentation, each weighted roughly equally.

### Cited Findings
- Earlier 4FIS events were small evening formats, not 24h events.
  - **4FIS Hackathon, 14 Apr 2025**: 18:00–21:45, real-estate price modelling on a real dataset, teams of up to 8, beginners welcome. No criteria, prizes or winners were published. — [4fis.cz/vzdelavacky-akce/4fis-hackathon](https://4fis.cz/vzdelavacky-akce/4fis-hackathon/)
  - **4FIS MiniHackathon, 21 Nov 2025**: a 3.5-hour sprint with 6 self-chosen briefs (pub-price scraper, study-spot map, festival visual, and others) and teams of 1–4. No criteria or winners were published. — [4fis.cz/vzdelavacky-akce/4fis-minihackathon](https://4fis.cz/vzdelavacky-akce/4fis-minihackathon/)
- UP Olomouc "Hackathon 2024 – Když data promluví" rules:
  - Required presentation elements: "název týmu a jeho složení, název projektu, použitá data, stručný popis řešení (formou schématu), popis výstupů (včetně ukázky), využitelnost výstupů a kritický SWOT analýza".
  - Criteria (0–10 each): "inovativnost …, zpracování (kvalita a správnost zpracování, promyšlenost celkového řešení), využitelnost (… business aspekt), udržitelnost …, prezentace (grafika, prezentování, diskuse)".
  - Jury: "zástupci přislibujícího a partnerů".
  - — [hackathon.upol.cz rules PDF](https://hackathon.upol.cz/wp-content/uploads/2024/09/pravidla.pdf)
- Same UP Olomouc rules, on AI and scope:
  - "Využití umělé inteligence … není organizátorem zakázáno. Podmínkou … je podrobně specifikovat způsob a míru využití umělé inteligence … Předmětem hodnocení bude vlastní práce soutěžního týmu."
  - If the full scope is too large, finish some parts and "podrobně popíše koncepci celého řešení".
  - — [hackathon.upol.cz rules PDF](https://hackathon.upol.cz/wp-content/uploads/2024/09/pravidla.pdf)
- MLH's recommended rubric for Hack Days: Technical implementation ("Does the project work…"), Creativity, Learning and ambition, Demo and clarity ("Can the team clearly explain the problem, solution, and implementation?"), and Partner eligibility ("Does the project satisfy the assigned partner's specific requirements?"). — [MLH Hack Days guide](https://hackdays-guide.mlh.com/run-your-event/project-submissions)
- A summary of MLH judging says most rubrics weight technical difficulty, originality, usefulness and presentation, with technical difficulty about 25%. Judges want a working implementation, not a mockup. Code quality itself is not judged. — [hackathon.exchange MLH guide (secondary)](https://hackathon.exchange/guides/how-to-prepare-for-mlh); [MLH rules repo](https://github.com/MLH/mlh-hackathon-rules/blob/master/Rules.md)
- Junction criteria have varied by year: Innovation (2023); Technical Implementation and "Wow-factor" (2017); multiple technologies, Design/UX, Real-World Impact (2016). Partner tracks are judged on the partner's own criteria. — [junction.devpost.com](https://junction.devpost.com/); [junction2017.devpost.com](https://junction2017.devpost.com/); [junction2016.devpost.com](https://junction2016.devpost.com/)

### Inferences
- Without official criteria, prepare for a rubric that covers all of these:
  - **Challenge fit**: the story is verifiably in the data, not just a label.
  - **Technical quality and correctness**: relational integrity, plausible distributions.
  - **Innovation**: for example, a narrative-to-simulation pipeline or an automatic "story recovery" check.
  - **Usability**: teaching datasets with an answer key, testing BI tools.
  - **Presentation**: schema plus a live demo.
- The challenge text says "musí jít dohledat v samotných datech", so the decisive demo is probably a **round trip**. Story in, dataset out, then an independent analysis, ideally SQL plus a chart, rediscovers the injected events: dates, effect sizes, affected segments. A machine-checkable "answer key" plus a validation report fits both MLH's "partner eligibility" and the UP Olomouc "správnost zpracování" criterion.
- Following the Czech norm, state openly where an LLM is used (parsing the story into a scenario spec) and where it is not (deterministic or statistical simulation with a seed). Faculty judges are likely to distrust LLMs inventing rows directly.
- Include a short critical SWOT or limitations slide. It is standard in Czech academic hackathons and shows self-awareness.

### Gaps
- I could not confirm that 4FIS uses a 0–10 multi-criteria sheet. The UP Olomouc rubric is only a proxy.
- I could not confirm 4FIS's policy on AI or pre-written code.

## Past winners at FIS VŠE / Czech data hackathons and why they won

### Takeaway
Public evidence on why teams won is thin. The best-documented FIS win was at an **external** Deepnote "AI & Data Hackathon". That 24h project was a working end-to-end AI pipeline with an interface: OCR, then an ML adapter, then an LLM, then a Streamlit UI. Organizers published no 4FIS winners.

### Cited Findings
- FIS students Samuel Krúžka, Simona Dohová and Petr Nguyen won Deepnote's 24h "AI & Data Hackathon". Their "AI-powered OCR Financial Analyzer" used Amazon Textract to extract data from financial documents, processed it through a custom ML adapter, and analyzed it with LLMs via Amazon Bedrock. It pulled real company data through the Tavily API and presented results in a Streamlit UI. The prize was USD 2,000 plus USD 30,000 in Deepnote credits. The article does not give judging criteria. — [fis.vse.cz news](https://fis.vse.cz/aktuality/studenti-fis-vyhrali-ai-data-hackathon/)
- The ML/AI Hackathon 2025 (DCÚK with ČVUT Děčín) was a 24h event with four tasks. It published winners (Koranderium, Lookey, Křížová výprava) but no project details or criteria. — [dcuk.cz](https://dcuk.cz/novinky/hackathon-ml-ai-2025-kdyz-se-data-potkaji-s-kavou-kodem-a-velkymi-napady/)
- 4FIS event pages for 2025 publish no winners. — [4fis.cz hackathon 2025](https://4fis.cz/vzdelavacky-akce/4fis-hackathon/); [4fis.cz minihackathon](https://4fis.cz/vzdelavacky-akce/4fis-minihackathon/)
- Historical precedent: the Czech "Enterprise Data Hackathon" (2014) had teams "drilling" into **fictitious data of Česká spořitelna**. Synthetic corporate datasets have long been used as hackathon material in CZ. — [Lupa.cz](https://www.lupa.cz/clanky/enterprise-data-hackathon-2014/) (title/snippet only; not fetched in full)

### Inferences
- The FIS win that FIS itself publicized was an end-to-end working pipeline that combines cloud LLM APIs with classic data processing and a simple UI. The faculty clearly sees cloud LLM services as legitimate. A Streamlit-style demo is a known-good format there.

### Gaps
- I found no winner write-ups for any 4FIS event, and no statements from FIS jurors about what they value.

## Likely judges and what would impress them on a synthetic-data challenge; relevant FIS courses

### Takeaway
The judges for this challenge are likely FIS academics, plus partner representatives (Nova/Oneplay, Česká spořitelna) and 4FIS organizers. FIS teaches knowledge discovery (CRISP-DM, KDD), databases, analytics and reporting. A generator that produces **relational teaching or test datasets with a hidden, verifiable "answer key"** maps directly onto those courses.

### Cited Findings
- FIS's Data Engineering minor specialization (4DI) includes the following courses — [fis.vse.cz 4DI](https://fis.vse.cz/magisterske-studium/vedlejsi-specializace/4di); [kizi.vse.cz 4DI](https://kizi.vse.cz/magisterske-studium/vedlejsi-specializace-datove-inzenyrstvi-4di-copy-2/) (via search summary):
  - Mandatory: 4IZ450 Dobývání znalostí z databází, 4IZ460 Pokročilé přístupy k dobývání znalostí z databází, 4IT403 Základní analytika a reporting.
  - Electives: 4IT218 Databáze, 4IT509 Nástroje pro podporu business analytiky.
- The 4IZ460 course page says it covers automatic hypothesis formation and practical analysis of large real datasets. — [vsewiki 4IZ460](https://vsewiki.cz/predmet/4IZ460)
- 4IZ260 (Úvod do dobývání znalostí z databází) teaches the KDD process, CRISP-DM and data preprocessing. — [studentino 4IZ260](https://www.studentino.cz/vse/fis/4iz260-69757)
- Partners on the jury are explicitly invited. — [hackathon.4fis.cz](https://hackathon.4fis.cz/)

### Inferences
- **Teaching angle.** Instructors in 4IZ260/450/460, 4IT218 and 4IT403 need fresh datasets every semester that contain known patterns:
  - an injected seasonality, a churn event after a price change, a fraud ring, a supplier failure;
  - so that student analyses can be graded against an answer key;
  - and so that each student or team can get a unique seed-variant, which stops copied answers.
  - This directly answers "why would FIS want this", and it is very likely the motivation behind a faculty-set challenge.
- **Statistical rigor that will impress statistics and econometrics faculty:**
  - realistic marginal distributions (heavy-tailed order values, Poisson arrivals, weekly and annual seasonality, Czech holidays);
  - consistent referential integrity across tables (customers → orders → order_items → products, employees, events);
  - controllable effect sizes and noise;
  - reproducibility through seeds;
  - a validation report that runs detection tests (changepoint, difference-in-differences, cohort retention) and shows the story is recoverable but not trivially obvious.
- **The KIZI or knowledge-engineering angle:** an explicit, inspectable scenario spec (a JSON/YAML "story graph" of entities, events, causal effects) between the LLM and the simulator. Judges can audit it, and it separates "AI understanding" from "simulation".
- **Czech context:** Czech names, addresses, IČO-like IDs, CZK, Czech public holidays, and optionally a Czech-language story input. Partners from Nova or ČS would relate to scenarios such as "a viewership drop after a schedule change" or "a bank branch closure shifting customers to mobile".
- **Difficulty knobs**, for example "easy / medium / hard to detect", tie the tool to teaching and show depth.

### Gaps
- I found no FIS course page that explicitly mentions synthetic or generated teaching datasets. The teaching use case is inferred from the course content, not confirmed.
- I found no public jury list, and no named FIS academic attached to Story2Data.
