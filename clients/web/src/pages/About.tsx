// About "/about": the technical part. Every measured number names its source (DECISIONS.md or
// docs/PLAN.md); nothing here is estimated. The live panels read GET /v1/stats every 5 s.
import { useEffect, useRef, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { animate, createScope, onScroll } from 'animejs'
import { statsOptions, type Stats } from '../api'
import { dateTimeCs, duration, intCs, num } from '../format'

const REPO = 'https://github.com/michalomegalul/hackathon-27-12-2026'
const BLOB = `${REPO}/blob/main`
const asset = (f: string) => `${import.meta.env.BASE_URL}${f}`

const link = 'text-slate-200 underline decoration-line underline-offset-2 hover:decoration-slate-400'
const Src = ({ file, label }: { file: string; label: string }) => (
  <a href={`${BLOB}/${file}`} className="font-mono text-[11px] text-slate-500 hover:text-slate-300">
    {label}
  </a>
)

function Panel({ title, children, className = '' }: { title: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`border-t border-line pt-5 ${className}`}>
      <h2 className="mb-3 font-semibold">{title}</h2>
      {children}
    </section>
  )
}

// ---- 1. the pipeline -----------------------------------------------------------------------

type Step = { n: string; what: string; how: string; ex: ReactNode; src: [string, string] }

/** One real example per step: the hackathon brief (examples/stories/brief.yaml) and its measurements. */
const STEPS: Step[] = [
  {
    n: 'Prompt',
    what: 'Firma a příběh česky, jedna zpráva.',
    how: 'Nikde v datech se pak neobjeví slovo „pokles“ – příběh je vidět jen v číslech.',
    ex: <q className="text-slate-200">Od dubna 2026 klesly tržby o 5 %, u všech zákazníků, ve všech kanálech i městech.</q>,
    src: ['examples/stories/brief.yaml', 'brief.yaml'],
  },
  {
    n: 'Spec',
    what: 'Gemma 4 z textu vyplní JSON schéma; Pydantic ho zkontroluje, chyby jdou zpět modelu.',
    how: 'Číslo, které příběh řekne, je fakt: kalibrace ani obtížnost ho nemění (size_stated).',
    ex: <code className="text-[12px] text-slate-200">purchase_rate −0,05 · size_stated: true · od 2026-04-01 · všichni</code>,
    src: ['DECISIONS.md#L999', 'DECISIONS 90, 92'],
  },
  {
    n: 'Data',
    what: 'Numpy simulace den po dni vyrobí propojené tabulky; dvojče má stejný seed a žádný příběh.',
    how: 'Událost násobí nákupní frekvenci nebo riziko odchodu jen u zákazníků, kterých se týká.',
    ex: <span>80 000 zákazníků: simulace 9,3 s, dvojče 8,7 s, kalibrace 34,6 s</span>,
    src: ['DECISIONS.md#L1091', 'DECISIONS 100'],
  },
  {
    n: 'Detektiv',
    what: 'Statistický sken (STL, PELT + Binseg, rozdíl v rozdílech) hledá změny, aniž by příběh znal.',
    how: 'Čte jen analytické tabulky; skrytý klíč s odpověďmi je pro něj fyzicky nedostupný.',
    ex: <span>Příklad A, obtížnost easy: zdražení kávy našel v 5 z 5 seedů</span>,
    src: ['DECISIONS.md#L492', 'DECISIONS 61'],
  },
  {
    n: 'Skóre',
    what: 'Ověřovač pro každou událost jeden test: cíl proti kontrolní skupině, 28 dní před a po, placebo z.',
    how: 'Potvrzeno = správný směr, 95% interval bez nuly a z ≥ 3. Totéž na dvojčeti nesmí nic najít.',
    ex: <span>seed 2: −5,00 % [−8,2; −0,4], z 3,70 ✓ · dvojče +0,08 %, z 0,04</span>,
    src: ['DECISIONS.md#L999', 'DECISIONS 92'],
  },
  {
    n: 'Shrnutí',
    what: 'Věty z promptu napojené na graf a sloupec tabulky, kde se změnily, i se SQL, které to dokazuje.',
    how: 'Český příběh píše AI jen z potvrzených řádků; číslo, které v tabulce není, text zamítne.',
    ex: <span>„klesly tržby o 5 %“ → objednávky za den, příběh proti dvojčeti → orders.order_date</span>,
    src: ['DECISIONS.md#L851', 'DECISIONS 81'],
  },
]

function Pipeline() {
  const root = useRef<HTMLOListElement>(null)
  useEffect(() => {
    const scope = createScope({ root, mediaQueries: { reduce: '(prefers-reduced-motion: reduce)' } }).add((self) => {
      if (self?.matches.reduce) return
      // the line between the steps draws with the scroll; each node lights up as the line reaches it
      animate('.rail', {
        scaleY: [0, 1],
        ease: 'linear',
        autoplay: onScroll({ target: root.current!, enter: 'bottom-=25% top', leave: 'bottom-=25% bottom', sync: true }),
      })
      root.current!.querySelectorAll<HTMLElement>('.node').forEach((n) =>
        animate(n, {
          backgroundColor: ['oklch(0.21 0.012 260)', 'oklch(0.74 0.15 160)'],
          color: ['oklch(0.68 0.015 260)', 'oklch(0.16 0.01 260)'],
          duration: 250,
          autoplay: onScroll({ target: n, enter: 'bottom-=25% center', leave: 'top center', sync: 'play reverse' }),
        }),
      )
    })
    return () => scope.revert()
  }, [])

  return (
    <ol ref={root} className="relative grid gap-5">
      <span aria-hidden className="absolute top-3 bottom-3 left-[13px] w-px bg-line" />
      <span aria-hidden className="rail absolute top-3 bottom-3 left-[13px] w-px origin-top bg-accent" />
      {STEPS.map((s, i) => (
        <li key={s.n} className="relative grid grid-cols-[28px_minmax(0,1fr)] gap-x-4">
          <span className="node z-10 grid size-7 place-items-center border border-line bg-bg font-mono text-xs text-muted">{i + 1}</span>
          <div className="grid gap-1.5">
            <h3 className="font-medium leading-7">{s.n}</h3>
            <p className="text-sm text-slate-300">{s.what}</p>
            <p className="text-sm text-muted">{s.how}</p>
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-l-2 border-line pl-3 py-1 text-sm">
              {s.ex}
              <Src file={s.src[0]} label={s.src[1]} />
            </div>
          </div>
        </li>
      ))}
    </ol>
  )
}

// ---- 2. live stats (Grafana-style panels) ---------------------------------------------------

function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'good' | 'warn' }) {
  return (
    <div className="grid content-between gap-1 border-l-2 border-line pl-3 py-1">
      <div className="text-[11px] tracking-wide text-muted uppercase">{label}</div>
      <div className={`text-2xl font-semibold tabular-nums ${tone === 'good' ? 'text-[#73bf69]' : tone === 'warn' ? 'text-[#f2cc0c]' : 'text-slate-100'}`}>
        {value}
      </div>
      {sub && <div className="truncate text-[11px] text-slate-500">{sub}</div>}
    </div>
  )
}

/** Done jobs per hour over the last 24 h, as bars (the last bar is the current hour). */
function Timeline({ t }: { t: Stats['timeline'] }) {
  const max = Math.max(1, ...t.map((h) => h.jobs))
  return (
    <div className="grid gap-1 border-l-2 border-line pl-3 py-1">
      <div className="flex items-baseline justify-between text-[11px] tracking-wide text-muted uppercase">
        <span>Hotové běhy za hodinu, 24 h</span>
        <span className="normal-case tracking-normal text-slate-500">max {max}</span>
      </div>
      <div className="flex h-20 items-end gap-[3px]" role="img" aria-label="Počet hotových běhů po hodinách za posledních 24 hodin">
        {t.map((h) => (
          <div
            key={h.hour}
            title={`${dateTimeCs(h.hour)}: ${h.jobs} běhů${h.median_run_s ? `, medián ${duration(h.median_run_s)}` : ''}`}
            className="min-h-px flex-1 bg-[#73bf69]/80 hover:bg-[#73bf69]"
            style={{ height: `${(h.jobs / max) * 100}%`, opacity: h.jobs ? 1 : 0.25 }}
          />
        ))}
      </div>
      <div className="flex justify-between text-[10px] text-slate-500">
        <span>{t[0] && new Date(t[0].hour).toLocaleTimeString('cs-CZ', { hour: '2-digit', minute: '2-digit' })}</span>
        <span>teď</span>
      </div>
    </div>
  )
}

function LiveStats() {
  const { data: s, error } = useQuery(statsOptions())
  if (error) return <p className="text-sm text-rose-300">{error.message}</p>
  if (!s) return <p className="text-sm text-muted">Načítám…</p>
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="běhy celkem" value={intCs(s.jobs_total)} sub={`${intCs(s.jobs_done)} hotových, ${intCs(s.jobs_today)} dnes`} />
        <Stat
          label="teď běží"
          value={s.running ? `${Math.round(s.running.progress * 100)} %` : '–'}
          sub={s.running ? `${s.running.step ?? ''}${s.waiting ? `, ve frontě ${s.waiting}` : ''}` : s.waiting ? `ve frontě ${s.waiting}` : 'fronta volná'}
        />
        <Stat label="medián běhu" value={s.median_run_s === null ? '–' : duration(s.median_run_s)} sub="bez čekání ve frontě" />
        <Stat label="vygenerované řádky" value={intCs(s.rows_generated)} sub={`${intCs(s.customers_simulated)} zákazníků`} />
        <Stat
          label="potvrzené události"
          value={s.events_confirmed_pct === null ? '–' : `${num(s.events_confirmed_pct)} %`}
          sub="z testovaných řádků všech běhů"
          tone={s.events_confirmed_pct !== null && s.events_confirmed_pct >= 80 ? 'good' : 'warn'}
        />
        <Stat
          label="falešné poplachy dvojčete"
          value={s.twin_false_pct === null ? '–' : `${num(s.twin_false_pct)} %`}
          sub="dvojče bez příběhu „najde“ událost"
          tone={s.twin_false_pct !== null && s.twin_false_pct <= 10 ? 'good' : 'warn'}
        />
        <div className="col-span-2">
          <Timeline t={s.timeline} />
        </div>
      </div>
      <p className="text-[11px] text-slate-500">
        Živě z <code>GET /v1/stats</code>, obnovuje se každých 5 s. Počítá všechny běhy na tomto serveru, i testovací, takže se liší od měření níže.
      </p>
    </div>
  )
}

// ---- 3. measured numbers -------------------------------------------------------------------

const MEASURED: [ReactNode, string, [string, string]][] = [
  [<><b>87 %</b> událostí příběhu potvrzeno (26/30), dvojče <b>3 %</b> (1/30)</>, '11 různých příběhů, gemma4:26b bez cache, seed 7', ['DECISIONS.md#L921', 'DECISIONS 88, PLAN.md']],
  [<><b>8 z 11</b> specifikací platných na první pokus, zbytek na druhý</>, 'stejný běh 11 příběhů', ['DECISIONS.md#L921', 'DECISIONS 88']],
  [<>příklad A: <b>90 %</b> potvrzeno (easy i medium), hard 55 %, dvojče <b>0 %</b></>, '40 000 zákazníků, seedy 1–5', ['DECISIONS.md#L581', 'DECISIONS 65']],
  [<>zadání hackathonu (−5 % u všech): <b>5/5</b> seedů potvrzeno, dvojče 0/5</>, '160 000 zákazníků; při 80 000 je to 4/5', ['DECISIONS.md#L999', 'DECISIONS 92']],
  [<>regrese: A 5/6, B 5/6, dvojče vždy 0/6, každé SQL sedí s Pythonem</>, 'po změně velikostí z příběhu', ['DECISIONS.md#L1027', 'DECISIONS 93']],
  [<>spec 20–50 s, kalibrace + simulace + dvojče 2–48 s, ověření 0,4–2,4 s</>, 'na příběh, 11 příběhů', ['DECISIONS.md#L921', 'DECISIONS 88']],
  [<>simulace 160 000 zákazníků za <b>19,3 s</b></>, 'notebook, 18 jader', ['DECISIONS.md#L1091', 'DECISIONS 100']],
]

/** Test cases per file: test functions with their parametrize cases expanded, tests/*.py on 27. 11. */
const TESTS: [string, number, string][] = [
  ['test_api.py', 34, 'HTTP API: tokeny a role, fronta, ETA, 409 před koncem, sandbox dotazů (klíč s odpověďmi nedosažitelný), dvojče, klíče a DDL, historie, statistiky'],
  ['test_verify.py', 22, 'ověřovač: SQL dává stejná čísla jako Python, velký efekt potvrdí a dvojče ne, kurýři, meziroční kontrola, zadání hackathonu, žádné vymyšlené číslo v textu'],
  ['test_detective.py', 25, 'detektiv: kód ani loader nesahá na skryté schéma, známý skok najde do 3 dnů, čistý šum bez zlomu, kalendář vysvětlí Black Friday, vypravěč nesmí vymyslet událost'],
  ['test_compiler.py', 24, 'příběh → spec s mockovaným LLM: chyba jde zpět modelu, opravné pokusy, záloha na Claude, uvedené velikosti ve schématu'],
  ['test_sim.py', 13, 'simulátor: stejný seed = stejné soubory, cizí klíče, odchod podle zadání, zdražení v ceníku, vyprodané zásoby, předplatné, nepořádek jen v exportu'],
  ['test_score.py', 12, 'skóre detektivu: časování od začátku + zpoždění, segment, velikost, návnady, důsledky, placebo'],
  ['test_calibrate.py', 10, 'kalibrace: cílové z podle obtížnosti, stropy, rozšíření cíle, uvedené velikosti zůstávají'],
  ['test_llm.py', 10, 'LLM vrstva bez GPU: replay z cache, pravidla požadavku na Ollamu, cache podle modelu'],
  ['test_spec.py', 9, 'DSL: příklady jsou platné, sémantické kontroly'],
  ['test_texts.py', 5, 'české recenze a tikety z poolů, zástupné znaky'],
  ['test_integration.py', 2, 'proti skutečné Gemmě (přeskočí se, když není dostupná)'],
  ['test_pg.py', 1, 'export do Postgresu s klíči (jen s testovací databází)'],
]
const TESTS_TOTAL = TESTS.reduce((a, [, n]) => a + n, 0)

// ---- the page ------------------------------------------------------------------------------

export function About() {
  return (
    <div className="grid max-w-4xl gap-5">
      <div className="px-1">
        <h1 className="text-xl font-semibold tracking-tight">Jak to funguje</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Příběh firmy jde dovnitř, ven vyjde relační databáze, ve které se ten příběh opravdu stal, a důkaz: pro každou událost test a SQL. Stejný svět bez
          příběhu nesmí ukázat nic.
        </p>
      </div>

      <Panel title="Pipeline v šesti krocích">
        <Pipeline />
      </Panel>

      <Panel title="Živě ze serveru">
        <LiveStats />
      </Panel>

      <div className="grid gap-5 md:grid-cols-2">
        <Panel title="Stack">
          <ul className="grid gap-2 text-sm">
            <li>
              <b>Gemma 4 26b</b> přes Ollamu na GPU v homelabu – <span className="text-muted">jen pro spec a český příběh, nic mezi tím.</span>
            </li>
            <li>
              <b>numpy</b> – <span className="text-muted">simulace den po dni nad poli zákazníků, ne objekty.</span>
            </li>
            <li>
              <b>DuckDB</b> – <span className="text-muted">pracovní úložiště a SQL sandbox; export do Postgresu s klíči.</span>
            </li>
            <li>
              <b>statsmodels, ruptures, scipy</b> – <span className="text-muted">STL, detekce zlomů, párování.</span>
            </li>
            <li>
              <b>FastAPI</b> – <span className="text-muted">úlohy ve frontě, stav s odhadem času, dotazy, ZIP.</span>
            </li>
            <li>
              <b>React</b> – <span className="text-muted">Vite, TanStack Query, uPlot, React Flow, anime.js.</span>
            </li>
          </ul>
        </Panel>
        <Panel title="Proč je statistika deterministická">
          <div className="grid gap-2 text-sm text-slate-300">
            <p>AI je jen na okrajích: napíše specifikaci a na konci převypráví výsledek. Všechno mezi tím jsou seedovaná čísla a pevné testy.</p>
            <p className="text-muted">
              Stejný seed dá stejná data. Každý podsystém (nákupy, odchody, košík…) má vlastní proud náhodných čísel, takže změna jednoho neposune ostatní.
              Prahy jsou globální, stejné pro každý příběh i pro dvojče.
            </p>
            <p className="text-muted">
              Model nesmí vymyslet číslo: český text se zahodí, když obsahuje hodnotu, která není v tabulce potvrzených výsledků.
            </p>
          </div>
        </Panel>
        <Panel title="Dvojče">
          <p className="text-sm text-slate-300">Stejná firma, stejný seed, žádné události. Rozdíl mezi světy je přesně příběh.</p>
          <p className="mt-2 text-sm text-muted">
            Každý test běží dvakrát: na datech s příběhem má událost potvrdit, na dvojčeti nesmí. Když dvojče něco „najde“, je to falešný poplach a počítá se.
          </p>
        </Panel>
        <Panel title="Kalibrace">
          <p className="text-sm text-slate-300">Událost musí být v datech dohledatelná, jinak příběh nemá smysl.</p>
          <p className="mt-2 text-sm text-muted">
            Před simulací se každý efekt změří v jednotkách šumu ověřovacího testu na dvojčeti (jiný seed) a zvětší se, dokud nedosáhne cíle obtížnosti: z 5 /
            3,5 / 2,5. Pokles má realistický strop (−30 %). Velikost, kterou příběh výslovně řekne, se nemění.
          </p>
        </Panel>
      </div>

      <Panel title="Křivky">
        <div className="grid gap-4 md:grid-cols-2">
          <figure className="grid gap-2">
            <img src={asset('verify_curve_a.png')} alt="Podíl potvrzených událostí podle obtížnosti: příběh 0,9 / 0,9 / 0,55, dvojče 0" className="w-full bg-white" loading="lazy" />
            <figcaption className="text-xs text-muted">
              Ověřovač, příklad A, 40 000 zákazníků, 5 seedů: příběh 90 / 90 / 55 %, dvojče 0 %. <Src file="DECISIONS.md#L581" label="DECISIONS 65" />
            </figcaption>
          </figure>
          <figure className="grid gap-2">
            <img src={asset('detection_curve_a.png')} alt="Detektiv naslepo: F1 0,19 easy, 0,04 medium a hard" className="w-full bg-white" loading="lazy" />
            <figcaption className="text-xs text-muted">
              Detektiv naslepo, 10 000 zákazníků: F1 0,19 / 0,04 / 0,04. Hledat bez nápovědy je mnohem těžší, proto je hlavní důkaz ověřovač a detektiv je bonus.{' '}
              <Src file="DECISIONS.md#L492" label="DECISIONS 61, 62" />
            </figcaption>
          </figure>
        </div>
      </Panel>

      <Panel title="Naměřeno">
        <ul className="grid gap-2.5">
          {MEASURED.map(([what, how, [file, label]], i) => (
            <li key={i} className="grid gap-x-4 gap-y-0.5 text-sm sm:grid-cols-[minmax(0,1fr)_auto]">
              <span className="text-slate-200">{what}</span>
              <span className="sm:text-right">
                <Src file={file} label={label} />
              </span>
              <span className="text-xs text-muted">{how}</span>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel
        title={
          <>
            Testy <span className="font-normal text-muted">· {TESTS_TOTAL} v pytestu</span>
          </>
        }
      >
        <ul className="grid gap-1.5 text-sm">
          {TESTS.map(([f, n, what]) => (
            <li key={f} className="grid grid-cols-[2.2rem_minmax(0,1fr)] gap-x-3 sm:grid-cols-[2.2rem_10rem_minmax(0,1fr)]">
              <span className="text-right font-mono tabular-nums text-slate-300">{n}</span>
              <a href={`${BLOB}/tests/${f}`} className="font-mono text-xs leading-5 text-slate-400 hover:text-white">
                {f}
              </a>
              <span className="col-start-2 text-muted sm:col-start-auto">{what}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-[11px] text-slate-500">
          Spočítáno z <code>tests/*.py</code> (testovací funkce, parametrizace rozepsaná). Bez GPU a databáze běží všechny kromě 3:{' '}
          <code>uv run pytest -m &quot;not integration&quot;</code>.
        </p>
      </Panel>

      <Panel title="API a kód">
        <p className="text-sm text-muted">
          Všechno, co stránka dělá, umí i HTTP API:{' '}
          <a href="/docs" className={link}>
            /docs
          </a>{' '}
          (Swagger, odeslat příběh, stav, výsledek, SQL, ZIP).{' '}
          <a href={REPO} className={link}>
            Repozitář na GitHubu
          </a>
          , rozhodnutí s měřeními v{' '}
          <a href={`${BLOB}/DECISIONS.md`} className={link}>
            DECISIONS.md
          </a>
          .
        </p>
      </Panel>
    </div>
  )
}
