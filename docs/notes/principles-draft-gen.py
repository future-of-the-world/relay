#!/usr/bin/env python3
"""Builds taste-draft.html: the taste sections, the memory map, the capture path, the owner questions."""
import glob, html, os, re, sys, collections

OUT = sys.argv[1]
ROOT = os.path.expanduser("~/.claude/projects")
E = html.escape

# ---------- taste sections ----------
SECTIONS = [
 dict(n=1, name="Порядок: что идёт первым",
  rule="Сначала правильность, потом исправление найденного, потом дешёвое раньше дорогого при равной пользе, и только потом новое; новое не тащит за собой старое.",
  extra="""<ol class="prio">
<li><b>Правильность и проверка.</b> Рецензию не пропускают ради экономии: экономят на её форме (одна хорошая вместо нескольких), а не на её наличии.</li>
<li><b>Найденная ошибка не откладывается.</b> Ошибка внутри ветки исправляется до слияния; ошибка в другом месте встаёт в очередь выше всех новых возможностей. «Технического долга» нет.</li>
<li><b>Бесплатное раньше платного.</b> Сначала проверки кодом (они ничего не стоят), потом рецензия моделью, потом платные прогоны.</li>
<li><b>Новое не тащит старое.</b> Старые проекты и старые форматы не поддерживаются ради совместимости, если владелец единственный пользователь.</li>
<li><b>Новые возможности — по числу важности (IP),</b> которое задаёт владелец; IP, выбранный агентом, помечается как выбранный агентом.</li>
</ol>""",
  signal="Два дела спорят за очередь; хочется отложить найденную ошибку «на потом»; хочется сэкономить, пропустив проверку; порядок, названный владельцем, расходится с тем, что делается.",
  act="Назвать оба дела и пункт порядка, который ставит одно выше. Если порядок не решает (два новых дела без IP), это вопрос владельцу.",
  quotes=[("our review - fix - review flow is wrong we move in cycle fixing the same problems. One good review is better than several bad reviews, and cheaper","21.10"),
          ("Code checks run first - it's free / Then they passes - run review step, that have result and can store artifacts","22.10"),
          ("ok, guard and gate first after the trial","23.10")],
  example="23.10 владелец сказал «guard and gate first after the trial», но первыми слились правило вкуса и правило о данных, а охранник — третьим (решение № 58 на странице решений). С этим разделом ведущая сессия назвала бы расхождение до того, как брать вкус, и спросила бы, обгоняет ли он охранника.",
  basis="№ 11, 19, 24, 39, 43, 58 на странице решений; 24.10 о старом формате очереди; в arsenal — пять мерил потока (15.10)", guess=False),
 dict(n=2, name="Трата",
  rule="Каждая работа делается один раз и нужна кому-то; повтор, пустой отказ и вывод, который никто не читает, — сигнал остановиться.",
  extra="<p>Суть нынешнего правила <code>rules/taste.md</code> сохраняется целиком: серьёзность — повторяющаяся трата (на каждом прогоне или изменении) средняя и чинится до слияния, разовая — низкая; рецензент ищет трату, которую добавляет ветка; после слияния ведущая сессия называет встреченную трату и ставит её причины в очередь.</p>",
  signal="Та же работа второй раз (проверка без изменений, второй агент читает уже прочитанное, шаг повторён после отказа); отказ или красный шаг, не нашедший ничего плохого; вывод, который никто не читает; шаг, который нужен только другому скрипту; то, что уже покрыто более простым; часовое задание агенту ради мелкой правки.",
  act="Остановиться до следующего шага и сказать одной строкой с числом (прогоны, минуты). Взять более дешёвый путь, если он есть; если трата встроена в устройство — её причина становится пунктом исправления, а не обходом, который повторяют каждый раз.",
  quotes=[("Let's create a taste section, experimental. You feel discomfort when you recognize - you're used not effectively, you want to detect this and fix ... find similiar problems before you merge them to the repo, and find it after","23.10"),
          ("Трата лишь одна из секцих \"вкуса\"","24.10")],
  example="23.10, ветка «тесты core в быстрой проверке»: 3 отказа на пути слияния, не нашедшие ничего плохого, проверяющий запущен дважды, ~8 минут полной проверки потрачены, потому что исправитель доложил «зелёно» до коммита. 24.10: запись очереди не взята до рецензии — 2 лишних круга проверки.",
  basis="23.10 (правило вкуса), 21.10 «cheaper», в arsenal — «меньше, но длиннее агенты» (13–15.10), в общих — «макет за минуты» (19.10)", guess=False),
 dict(n=3, name="Выводимое не хранится",
  rule="Хранится только то, что нельзя вычислить; состояние выводится из событий с датой и из фактов (git, очередь, отчёты), а не записывается отдельным полем.",
  signal="Поле, которое повторяет то, что уже видно из других данных (status, state, updated_at, счётчик); журнал, написанный от руки, пересказывает то, что знает git; собранный файл (видео, рендер) кладётся в git рядом с исходником.",
  act="Заменить поле событием с датой и правилом проверки (closed_at, taken_at, dropped_at); состояние считать при чтении; в git хранить только воспроизводимые исходники.",
  quotes=[("При проектировании баз данных я сам категорически против полей status, они ничего не дают и их легко посчитать исходя из \"реального\" состояния объекта","24.10"),
          ("Вместо updated_at я помечаю событийно - closed_at, taken_at, dropped_at, у полей так же есть правила валидации","24.10")],
  example="Все 48 записей очереди relay хранят поле <code>state</code> (open, taken, done), хотя его можно вычислить из taken_by и closed_by. Владелец заметил это 24.10; с этим разделом рецензия формата очереди 22.10 нашла бы его до того, как поле появилось в каждой записи, и не понадобилась бы миграция в два шага.",
  basis="24.10 (status и событийные поля); № 28 «состояние из фактов» (22.10, не доверяет журналу от руки); в blogger — «только воспроизводимые исходники в git»; в ALIX — «статусы выводятся из вторичных меток» (16.10)", guess=False),
 dict(n=4, name="Для скрипта — структура, для человека — вид",
  rule="Повторяющиеся записи, поля которых извлекает скрипт, лежат в JSON/TOML со схемой и меняются одним скриптом; текст для людей и моделей остаётся прозой; числа хранятся простыми, показываются красиво.",
  signal="Скрипт ищет метку или число регуляркой в прозе; текст, который никто не разбирает, переводится в JSON; в хранилище лежит «1h 30m»; рецензия судит показ по удобству арифметики.",
  act="Задать вопрос-проверку: «это повторяющаяся запись, поле которой скрипт извлекает, считает или меняет?» Да — структура, схема, один пишущий скрипт. Нет — проза. Показ судить по читаемости.",
  quotes=[("I want to lock format - persist structured, operate with scripts","22.10"),
          ("We should store only structured data that can be splitted into repeated domain data, if this unstructured instructions or plain text - you don't need to store it in structured format","23.10"),
          ("My head can calc this, I care about your calculation, store in minutes plain numbers, show pretty format for me","22.10")],
  example="22.10 проверка перед слиянием считала «open n», ища слова в прозе проверяющего; теперь итоги лежат в JSON. В обратную сторону: задача «отчёты агентов в JSON» снята 23.10 — их читают люди и модели, скрипт полей не извлекает.",
  basis="№ 50, 51, 53, 55, 63 на странице решений", guess=False),
 dict(n=5, name="Факт — коду, смысл — модели",
  rule="То, что можно проверить точно, проверяет код (жёсткий список, тест); то, что требует понимания (намерение во фразе, верность ответа по смыслу, содержание картинки), решает модель, а код её только проверяет и измеряет.",
  signal="Модель сама решает правило безопасности или что считать «безвредным»; регулярка или список слов пытается поймать намерение владельца; код пытается сочинить то, что должна написать модель.",
  act="Факт — в код или жёсткий список. Смысл — в описание намерения для модели и в платные тесты на двух языках, с опечатками и с фразами, которые не должны срабатывать.",
  quotes=[("model shouldn't decide by self","22.10"),
          ("a, model should recognize it, I can typo text in many languages, with misstypings and common language errors","21.10")],
  example="23.10 убран крючок, ловивший слова о расходах: навык настройки теперь запускается по пониманию модели. До сужения описания — 2 ложных срабатывания из 15, после — 27 из 27 ($3.14). И наоборот: что сохраняет метку проверки после новых коммитов, решает жёсткий список файлов, а не модель (22.10).",
  basis="№ 9, 23, 38, 39, 67 на странице решений; в SIGHT — «правила не рисуют картинку» (10.02)", guess=False),
 dict(n=6, name="Причина, а не симптом",
  rule="Когда беда повторяется, ищут причину и чинят правило за находкой, а не один пример; повторные прогоны только доказывают исправление.",
  signal="Тот же вид сбоя второй раз; предложение «прогнать ещё раз»; заплатка рядом с прошлой заплаткой; три мелких исправления одного места.",
  act="Перечислить гипотезы (общее состояние нескольких участников, медленная среда, гонки, сменилась форма ответа) и собрать улики на каждую; одна переделка вместо серии заплаток; исправление доказать случаями рецензента.",
  quotes=[("agent is not deterministic, you need more analysis of cause rather than more runs, common cause of flakiness in the code - shared state, slowness of environment, races","22.10"),
          ("our review - fix - review flow is wrong we move in cycle fixing the same problems","21.10")],
  example="21.10 охранник: рецензии, смотревшие только на последнее исправление, находили следующую дыру рядом с прошлой — 20 обходов, потом 4, потом 2. 23.10 вместо трёх заплаток на проверку взята одна переделка (№ 62).",
  basis="№ 11, 35, 62 на странице решений; в ALIX — «повторяющиеся сбои значат устройство» (13.10)", guess=False),
 dict(n=7, name="Просто и без лишних частей",
  rule="Из двух путей выбирают тот, где меньше частей; не добавляют сервер, формат или слой, если хватает git и скрипта; новое встраивают в своё место, а не прикручивают сбоку.",
  signal="Отдельный сервис там, где хватит локального скрипта; второй формат «для совместимости»; более дорогой инструмент при равном качестве; опция, прикрученная к одному экрану или шагу.",
  act="Предложить путь без лишней части и назвать, что он теряет, числом или примером.",
  quotes=[("just git ... agent can manage scripts and run it","22.10"),
          ("I think we're reject Jev with cause Haiku is still cheap but better","22.10"),
          ("После миграции нам уже не нужно будет поддерживать старый формат, relay никем кроме меня не используется так что проблем не будет","24.10")],
  example="22.10 отказ от отдельного сервера проверок (Woodpecker): проверка — локальные скрипты, их итоги лежат в git рядом с меткой. 24.10 второй шаг миграции очереди убирает чтение старого формата вместо того, чтобы держать оба.",
  basis="№ 37, 40, 43 на странице решений; 24.10; общее правило «Keep it simple»; в общих — «перестраивать, а не прикручивать» (UI)", guess=False),
 dict(n=8, name="Владелец читает, а не вспоминает",
  rule="Каждое сообщение понятно через два дня без разговора: на родном языке владельца, простыми словами, с живым примером; время — в минутах работы агентов и доле лимита.",
  extra="<p>Почти всё это уже записано в правиле «Как со мной работать». Раздел вкуса добавляет сигнал: момент, когда сообщение вот-вот уйдёт тонким.</p>",
  signal="Вопрос в одну-две фразы без вступления; в ответе внутреннее имя (ветка, файл, команда) вместо того, что это делает; оценка в человеко-часах; термин без определения; ответ на английском.",
  act="Дописать вступление (механизм, живой пример, что меняет ответ), заменить имена на действия, перевести оценку в минуты агентов и % лимита.",
  quotes=[("what if I return to this session after the 2 days, you put a single or two sentences in question now, why you cut this, I can read more, I need to read more","22.10"),
          ("My native lang is russian - I don't like speak in English","23.10"),
          ("Всё это время я общался с тобой на ломанном английском, у меня есть опасения, понимал ли ты меня так как этого хотел","23.10")],
  example="21.10 оценки «5–7 ч» оказались непроверенными человеко-часами; замер того же дня: полный цикл «сборка — рецензия — исправление — проверка» около 30 минут агентов и 2% пятичасового лимита.",
  basis="№ 6, 27, 33, 69, 71 на странице решений", guess=False),
 dict(n=9, name="Решай сам внутри принципов",
  rule="Решение, которое следует из принципов и записанных решений, принимается и сообщается после; владельцу идёт только его выбор: компромисс, число, срез объёма, то, что увидит человек. Редкие крайние случаи не выносятся.",
  signal="Вопрос, на который уже отвечает принцип или прошлое решение; вопрос о редком крайнем случае; ожидание согласия на уже разрешённое (платные проверки до $50 в день).",
  act="Найти записанное решение; решить; записать с пометкой «владелец может отменить»; сообщить после.",
  sub=("предположение", "Вопрос владельца вида «почему бы не…» (№ 29, 51, 55) — это вопрос, а не указание: сначала ответ с рекомендацией, действие — после его слова. Опирается на 0 решений владельца: это мой вывод из того, что такие вопросы трижды выполнялись как указания. Страница решений уже спросила об этом; ваш ответ там решает и этот пункт."),
  quotes=[("a, you can run paid checks without my approve, increase limit to 50$","22.10"),
          ("Меня устраивают твои рекомендации","24.10")],
  example="24.10 устройство «долгое задание запускает ведущая сессия в фоне, а не ожидающий агент» решено без вопроса: его решает принцип «никакого агента, который ждёт». Владелец принял слияние словами «Да, можешь слить».",
  basis="№ 49, 57 (2c «больше не спрашивать»), 24.10; в ALIX — «решаю всё внутри принципов» (12.10); в arsenal — «владелец смотрит принципы, а не отдельные решения» (15.10); в общих — «не выносить редкие случаи»", guess=False),
]

# ---------- memory map ----------
SEC = {s["n"]: s["name"] for s in SECTIONS}
def T(n): return f"Вкус: {n}. {SEC[n]}"
def R(f): return f"Правило rules/{f}"
def G(k): return f"projects.toml [global] {k}"
def D(p): return f"Документы проекта: {p}"
X = "Удалить: устарело"
# kind: В = вкус (как решать), П = правило (уже есть или новая строка), Ф = факт
RELAY = collections.OrderedDict([
 ("taste-means-judgement", ("В", T(1) + " и вводная часть правила вкуса", "Само определение вкуса; станет первой строкой rules/taste.md.")),
 ("always-review-fixes", ("П", R("delegation.md") + "; пример для " + T(6), "Форма рецензии уже в правиле («One good review, not several»); память хранит историю 20→4→2.")),
 ("display-pretty-store-plain", ("В", T(4), "Принцип владельца о хранении и показе.")),
 ("persist-structured-operate-scripts", ("П", R("structured-data.md") + "; " + T(4), "Правило уже есть; в памяти пометка, что пример «hand-backs» в правиле устарел — это пункт исправления правила.")),
 ("natural-language-triggers", ("В", T(5), "Смысл фразы — модели, а не регулярке.")),
 ("flaky-means-find-the-cause", ("П", R("quality-gate.md") + "; " + T(6), "Правило о нестабильных тестах уже есть; причина-сначала — вкус.")),
 ("questions-carry-context", ("П", R("working-with-me.md"), "Формат вопросов уже закреплён в правиле дословно.")),
 ("estimates-in-agent-time", ("П", R("working-with-me.md") + " (новая строка); " + T(8), "В правиле нет строки об оценках в минутах агентов и % лимита; замеры 21.10 — в документы relay.")),
 ("stop-agents-after-handback", ("П", R("working-with-me.md") + " (уже: «prune idle agents at once») и навык delegate", "Правило есть; память добавляет точное действие (TaskStop сразу после отчёта) — оно идёт в навык ведущей сессии.")),
 ("paid-checks-preapproved", ("Ф", G("paid_checks_daily_cap_usd = 50") + "; пример для " + T(9), "Число — настройка, не принцип; разрешение без вопроса — пример вкуса 9.")),
 ("owner-billing-subscription", ("Ф", G("billing = \"subscription\"") + " → строка в общих инструкциях", "Факт о владельце, как родной язык: от него зависит, как говорить о цене (доля лимита, а не доллары).")),
 ("owner-native-language", ("Ф", G("native_language") + " (уже есть)", "relay уже хранит язык и пишет строку «My native language: Russian.»; память дублирует.")),
 ("relay-cost-calibration", ("Ф", D("relay (docs/, история замеров)"), "Замер 21.10 (relay на 36% ниже /cost) устарел как живое знание: после исправления расхождение 4,5%. Остаётся историей.")),
])
OTHER = {
 # ALIX
 "add-diagnostics-review-3": ("Ф", X, "Находки рецензии 28.09, изменение слито."),
 "after-add-backtest-merge": ("Ф", X, "Состояние на 28–29.09."),
 "alix-project": ("Ф", D("ALIX"), "Что такое проект."),
 "approval-section-in-reports": ("П", X, "Сам помечен SUPERSEDED."),
 "autonomy-and-decider": ("В", T(9), "Решать внутри принципов, сообщать после."),
 "breadth-of-trials": ("Ф", D("ALIX"), "Направление проекта."),
 "bybit-demo-key-env": ("Ф", D("ALIX"), "Справка об окружении."),
 "config-over-runtime": ("Ф", D("ALIX (docs/principles.md)"), "Принцип одного проекта."),
 "continue-past-handover": ("П", R("openspec.md"), "Не прерывать применение изменения ради передачи сессии — касается любого проекта с OpenSpec."),
 "decision-maker-research-direction": ("Ф", D("ALIX"), "Направление исследований."),
 "demo-mainnet-naming": ("Ф", D("ALIX"), "Словарь проекта."),
 "demo-only-until-proven": ("Ф", D("ALIX"), "Правило проекта о деньгах."),
 "document-knowledge-gaps": ("П", R("working-with-me.md") + " (уже есть)", "«Record domain knowledge I lacked in the project docs»."),
 "fast-backtests-principle": ("Ф", D("ALIX (уже правило 15 docs/principles.md)"), "Уже записано в проекте."),
 "flaky-tests-unacceptable": ("П", R("quality-gate.md") + " (уже есть)", "max(20, ⌈3/p⌉) уже в правиле."),
 "keep-trading-through-db-failure": ("Ф", D("ALIX"), "Правило проекта."),
 "kill-switch-marker-race": ("Ф", D("ALIX (очередь работ)"), "Открытая работа проекта."),
 "living-docs": ("Ф", D("SIGHT"), "Перешло в SIGHT."),
 "monitor-every-run": ("Ф", D("ALIX"), "Правило проекта."),
 "no-global-state": ("Ф", D("ALIX"), "Принцип проекта; общий смысл уже в " + T(6) + " (общее состояние как причина)."),
 "no-versioning-before-trading": ("Ф", D("ALIX"), "Правило проекта."),
 "observability-core": ("Ф", D("ALIX"), "Требование проекта."),
 "observability-roadmap": ("Ф", D("ALIX"), "Планы проекта."),
 "outbound-writes-outbox": ("Ф", D("ALIX"), "Правило проекта."),
 "parallel-apply-deps": ("Ф", D("ALIX"), "Приём для рабочих папок проекта."),
 "parallel-ci-plan": ("Ф", D("ALIX (очередь работ)"), "Открытая работа."),
 "perpetuals-decision": ("Ф", D("ALIX"), "Решение по продукту."),
 "post-fill-failure-policy": ("Ф", D("ALIX"), "Решение по продукту."),
 "principles-not-numbers": ("В", "Роль thinker в relay (уже: «каждое число — настройка»)", "Уже в общей основе мыслителя."),
 "profit-first-priority": ("Ф", D("ALIX"), "Приоритет проекта."),
 "project-lead-flow": ("П", X + "; довод для " + T(3), "Поток с ведущими отменён 16.10; «статусы выводятся из меток» — довод раздела 3."),
 "repeated-failures-mean-structure": ("В", T(6), "Повтор сбоя — искать устройство."),
 "return-target-and-autonomy": ("Ф", D("ALIX"), "Цель проекта."),
 "scoped-tests-local-gate-remote": ("Ф", D("ALIX"), "Порядок проверок проекта (relay выбрал локальные скрипты)."),
 "self-healing-principle": ("Ф", D("ALIX"), "Принцип проекта."),
 "session-handover": ("Ф", X, "Состояние 16.10, поток с ведущими отменён."),
 "shadow-virtual-account": ("Ф", D("ALIX"), "Ожидание владельца по продукту."),
 "sight-project": ("Ф", D("SIGHT"), "Что такое проект."),
 "surface-hidden-gaps": ("В", T(8), "Показывать расхождение между тем, что владелец думает, и тем, что делает код."),
 "tech-debt-program": ("Ф", X, "Программа 29.09; теперь «долга нет» — " + T(1) + "."),
 "tigerstyle-principles": ("В", T(1) + "; " + D("ALIX"), "TigerStyle — источник «найденное не откладывается»."),
 "tree-orchestration": ("П", X, "Отменено 16.10 (откат к чистому потоку)."),
 "typesafe-key-env": ("П", R("shell.md") + " (уже есть)", "«zsh -ic» для переменных из ~/.zshrc."),
 "user-jurisdiction": ("Ф", G("jurisdiction"), "Факт о владельце; ограничивает выбор сервисов в любом проекте."),
 "user-role-and-communication": ("В", T(8) + "; " + T(9), "Владелец держит принципы, а не механизмы."),
 "worktree-only-workflow": ("П", R("git.md") + " (уже есть)", "Работа только в рабочих папках веток."),
 "zsh-path-variable": ("П", R("shell.md") + " (уже есть)", "Переменная path."),
 # blogger, cartoons
 "judge-motion-from-video": ("П", R("product-work.md"), "Судить движение по ролику — частный случай «показать в настоящей среде»."),
 "media-are-build-artifacts": ("В", T(3), "В git только воспроизводимые исходники."),
 "drawing-quality": ("Ф", D("cartoons"), "Планка качества проекта."),
 "project-start": ("Ф", D("cartoons"), "Состояние проекта на 18.10."),
 # Glonass
 "go-codegen-tool-directives": ("Ф", D("Glonass Go-репозитории (AGENTS.md)"), "Привычка в Go-коде."),
 "fnis-dev-testing-via-pi-daemon": ("Ф", D("fnis-adapter"), "Справка."),
 "secret-exposure-notices-conversation-only": ("П", R("secrets.md"), "Новая строка: сообщение об утечке — только в разговоре."),
 "etl-engine-plan": ("Ф", D("ksim-adapter / etl"), "Решения по задаче."),
 "les-12996-research": ("Ф", D("ksim-adapter"), "Исследование задачи."),
 "dwh-dev-only": ("П", R("glonass.md"), "Запрет на прод-DWH — правило безопасности для всех репозиториев Glonass."),
 "les-12990-links": ("Ф", D("sorm-adapter"), "Ссылки задачи."),
 "les-12990-status": ("Ф", D("sorm-adapter"), "Состояние задачи на 22.10."),
 "glonass-common-env-access": ("Ф", D("Glonass common"), "Справка о стендах."),
 "glonass-tooling-quirks": ("П", R("glonass.md"), "Ограничения инструментов glonass_* касаются всех задач Glonass."),
 "kiask-trolleybus-les-12726-state": ("Ф", X, "Состояние на 08.10."),
 "tracker-task-orchestrator-workflow": ("П", R("glonass.md"), "Как вести задачи Tracker."),
 "doc-as-code-update-flow": ("Ф", D("doc/documentation"), "Справка."),
 "glonass-gitlab-push-over-direct-ssh": ("П", R("glonass.md"), "Как пушить в GitLab Glonass — для всех репозиториев."),
 # arsenal, linter
 "adopt-linter-tool-handover": ("Ф", X, "Состояние на 11.10."),
 "arsenal-daemon-mode-decider": ("В", T(9), "Принципы и направление — от владельца, остальное решается."),
 "arsenal-direction": ("Ф", D("arsenal"), "Направление проекта."),
 "arsenal-future-picture": ("Ф", D("arsenal"), "Где лежит разбор."),
 "arsenal-issue-create-no-propose-gate": ("Ф", D("arsenal"), "Разрешение проекта."),
 "context-budget-settings-plan": ("П", X, "План 05.10; бюджет теперь в " + R("front.md") + " (400k)."),
 "fewer-longer-agents": ("П", R("delegation.md") + " (уже есть); " + T(2), "«fewer, longer agents» уже в правиле."),
 "flow-quality-metrics": ("В", T(1), "Пять мерил потока владельца — порядок ценностей."),
 "orchestrator-context-budget": ("П", R("front.md") + " (уже есть, новее)", "600k устарело, правило держит 400k."),
 "proactive-improvement": ("В", T(2), "Замечать трение без просьбы — сигнал вкуса."),
 "review-principles-not-decisions": ("В", T(9), "Владелец смотрит принципы."),
 "rollback-to-clean-flow": ("П", X, "История 16.10; теперь поток — relay."),
 "woodpecker-pr-edit-cancels-pipeline": ("Ф", D("arsenal"), "Справка о CI."),
 "arsenal-bug-fix-authority": ("Ф", D("linter"), "Разрешение проекта."),
 "arsenal-measurement-setup": ("Ф", D("linter"), "Справка."),
 "autofix-system-direction": ("Ф", D("linter"), "Направление; «система, а не перебор токенами» — довод для " + T(6) + "."),
 "autonomous-issue-workflow": ("Ф", D("linter"), "Разрешение проекта."),
 "config-migration-style": ("Ф", D("linter"), "Решения проекта."),
 "linter-kb-pipeline-direction": ("Ф", D("linter"), "Решения проекта."),
 "nilaway-upstream-issue": ("Ф", D("linter (очередь работ)"), "Открытое дело."),
 # humar / glyph
 "bun-not-node": ("Ф", D("Glyph"), "Выбор инструментов проекта."),
 "glyph-buyer-questions": ("Ф", D("Glyph"), "Правило проекта."),
 "glyph-hosting": ("Ф", D("Glyph"), "Справка."),
 "glyph-lead-merges": ("П", D("Glyph") + " — проверить", "Ведущие отменены 16.10, а общее правило git требует слова владельца; оставить только после его подтверждения."),
 "glyph-project": ("Ф", D("Glyph"), "Что такое проект."),
 "glyph-run-as-lead": ("П", X, "Ведущие отменены 16.10."),
 "glyph-testnet-wallet": ("Ф", D("Glyph"), "Где лежит ключ (без самого ключа)."),
 "glyph-visual-questions": ("П", R("product-work.md") + " (уже есть)", "«что увидит человек»."),
 "vpn-fake-dns": ("Ф", D("relay: заметки о машине"), "Факт о машине, не о проекте."),
 # mind, noisegate, storyteller, shu, sight, strategy
 "carry-app-store-plan": ("Ф", D("Carry (mind)"), "План проекта."),
 "carry-handover-pointer": ("Ф", D("Carry (mind)"), "Указатель на файл передачи."),
 "carry-owner-working-style": ("П", R("product-work.md"), "Показывать макет и ждать «lock it» — уже в правиле о продукте."),
 "check-decisions-before-advising": ("В", T(9), "Сначала найти записанное решение."),
 "interactive-samples": ("Ф", D("Storyteller"), "Предпочтение по образцам."),
 "plain-language-for-readers": ("Ф", D("Storyteller"), "Частности общего правила."),
 "previews-keep-formatting": ("Ф", D("NOISEGATE"), "Правило проекта."),
 "blender-video-pipeline": ("Ф", D("shu"), "Справка."),
 "philosophy-notes-verbatim": ("Ф", D("shu"), "Куда записывать заметки."),
 "shu-project": ("Ф", D("shu"), "Что такое проект."),
 "guard-main-literal-paths": ("Ф", D("SIGHT"), "Особенность его крючка."),
 "rules-cannot-write-the-picture": ("В", T(5), "Модель пишет картинку, код проверяет."),
 "sight-direction": ("Ф", D("SIGHT"), "Направление проекта."),
 "target-is-the-prototype-form": ("Ф", D("SIGHT"), "Правило проекта."),
 "chatbattle-decisions": ("Ф", D("strategy"), "Решения по игре."),
 "chatbattle-idea-and-jev-probe": ("Ф", D("strategy"), "Идея и замер."),
 # home folder
 "ai-code-quality-bar": ("В", T(1), "Настоящая архитектура и хорошие тесты, а не «работает»."),
 "arbitrage-project": ("Ф", D("research"), "Что за проект."),
 "carry-game-project": ("Ф", D("Carry (mind)"), "Что за проект."),
 "clean-project": ("Ф", D("clean"), "Что за проект."),
 "default-branch-naming": ("П", R("git.md"), "Новая строка: главная ветка master, у Glonass — develop."),
 "fast-mockups-for-decisions": ("В", T(2), "Часовое задание ради мелкой правки — трата."),
 "improve-on-leaders": ("П", R("product-work.md") + " (уже есть)", "«starts from the leading apps» + где мы лучше."),
 "never-tell-user-what-they-know": ("П", R("product-work.md"), "Новая строка о подписях в интерфейсе."),
 "ngate-v2box-network-setup": ("Ф", D("relay: заметки о машине"), "Факт о машине."),
 "no-rare-case-choices": ("В", T(9), "Редкие случаи не выносить."),
 "own-product-goal": ("Ф", D("relay (цели владельца)"), "Цель владельца, к которой относится relay."),
 "principles-library": ("Ф", X, "~/principles заменён relay."),
 "relay-project": ("Ф", X, "relay знает себя сам."),
 "reorganize-ux-not-bolt-on": ("В", T(7), "Встраивать, а не прикручивать."),
 "show-ui-decisions-as-mockups": ("П", R("product-work.md") + " (уже есть)", "Показывать в настоящей среде."),
 "storyteller-project": ("Ф", D("Storyteller"), "Что за проект."),
 "study-reference-design-first": ("П", R("product-work.md"), "Новая строка: сначала прочесть стили образца."),
 "visible-probes-need-short-guards": ("П", R("verify.md"), "Новая строка: замер с окном на экране — секунды, не минуты."),
}

files = [f for f in glob.glob(ROOT + "/*/memory/*.md") if not f.endswith("MEMORY.md")]
folders = {os.path.dirname(f) for f in files}
seen = collections.OrderedDict()
for f in sorted(files):
    t = open(f, encoding="utf-8").read()
    m = re.search(r"^name:\s*(.*)$", t, re.M)
    n = m.group(1).strip() if m else os.path.basename(f)[:-3]
    proj = re.sub(r"^-Users-amidman-?", "", f.split("/")[-3]) or "домашняя папка"
    proj = re.sub(r"--claude-worktrees-.*|-\.worktrees-.*|-worktrees-.*", "", proj)
    proj = re.sub(r"^go-src-gitlab-aoglonass-ru-", "glonass/", proj)
    proj = re.sub(r"^go-src-go-amidman-dev-", "", proj)
    seen.setdefault(n, set()).add(proj)
relay_names = set(RELAY)
others = [n for n in seen if n not in relay_names]
missing = [n for n in others if n not in OTHER]
extra = [n for n in OTHER if n not in seen]
if missing or extra:
    sys.exit(f"unmapped: {missing}; stale map keys: {extra}")
relay_files = sorted(os.path.basename(f)[:-3] for f in glob.glob(ROOT + "/-Users-amidman-relay/memory/*.md") if not f.endswith("MEMORY.md"))
assert set(relay_files) == relay_names, (set(relay_files) ^ relay_names)

def dest_class(d):
    return "Удалить" if d.startswith("Удалить") else d.split(":")[0].split(" ")[0]
cnt = collections.Counter()
def bucket(d):
    if d.startswith("Вкус"): return "вкус"
    if d.startswith("Правило") or d.startswith("Роль"): return "правило"
    if d.startswith("projects.toml"): return "[global]"
    if d.startswith("Документы"): return "документы проекта"
    if d.startswith("Удалить"): return "удалить"
    return "другое"
KIND = {"В": "вкус", "П": "правило", "Ф": "факт"}
def rows(items, with_proj):
    out = []
    for n, (k, d, why) in items:
        cnt[bucket(d)] += 1
        proj = ", ".join(sorted(seen.get(n, {"relay"}))) if with_proj else ""
        out.append(f"<tr><td><code>{E(n)}</code>{'<br><span class=muted>'+E(proj)+'</span>' if with_proj else ''}</td><td><span class='kind k{k}'>{KIND[k]}</span></td><td>{E(d)}</td><td>{E(why)}</td></tr>")
    return "\n".join(out)
relay_rows = rows(RELAY.items(), False)
relay_cnt = dict(cnt); cnt.clear()
other_rows = rows(sorted(((n, OTHER[n]) for n in others), key=lambda x: (sorted(seen[x[0]])[0], x[0])), True)
other_cnt = dict(cnt)

# ---------- render ----------
def sec_html(s):
    q = "".join(f"<blockquote lang='{ 'ru' if re.search('[а-яА-Я]', w) else 'en'}'>«{E(w)}» <span class=muted>— {d}</span></blockquote>" for w, d in s["quotes"])
    sub = ""
    if s.get("sub"):
        sub = f"<p class='guess'><span class='badge'>{s['sub'][0]}</span> {E(s['sub'][1])}</p>"
    badge = "<span class='badge'>предположение</span>" if s["guess"] else ""
    return f"""<section class="taste" id="t{s['n']}">
<h3>{s['n']}. {E(s['name'])} {badge}</h3>
<p class="rule">{E(s['rule'])}</p>
{s.get('extra','')}
<dl>
<dt>Когда срабатывает</dt><dd>{E(s['signal'])}</dd>
<dt>Что делать</dt><dd>{E(s['act'])}</dd>
<dt>Слова владельца</dt><dd>{q}</dd>
<dt>Где изменило бы решение</dt><dd>{s['example']}</dd>
<dt>Основание</dt><dd class="muted">{E(s['basis'])}</dd>
</dl>
{sub}
</section>"""

def fmt_cnt(c):
    order = ["вкус", "правило", "[global]", "документы проекта", "удалить"]
    return ", ".join(f"{k} — {c.get(k,0)}" for k in order)

CSS = """
:root{--bg:#fbfaf7;--surface:#fff;--text:#1d1d1f;--muted:#5c5c63;--border:#dedbd3;--head:#f1efe9;--quote:#f6f3ea;--accent:#2f5fb3;--warn-bg:#fdf0d5;--warn-fg:#7a4d00;--kV:#e4ecfb;--kP:#e4f2e6;--kF:#f1efe9;}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#17171a;--surface:#1f1f23;--text:#ececef;--muted:#a5a5ad;--border:#3a3a41;--head:#2a2a30;--quote:#26262c;--accent:#8db3f5;--warn-bg:#3d3018;--warn-fg:#f3cf86;--kV:#22304a;--kP:#1f3a25;--kF:#2a2a30;}}
:root[data-theme="dark"]{--bg:#17171a;--surface:#1f1f23;--text:#ececef;--muted:#a5a5ad;--border:#3a3a41;--head:#2a2a30;--quote:#26262c;--accent:#8db3f5;--warn-bg:#3d3018;--warn-fg:#f3cf86;--kV:#22304a;--kP:#1f3a25;--kF:#2a2a30;}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;padding:24px 16px 48px;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans",sans-serif;font-size:16px;line-height:1.55}
main{max-width:960px;margin:0 auto}h1{font-size:1.6rem;margin:0 0 8px}h2{font-size:1.3rem;margin:40px 0 8px;border-bottom:1px solid var(--border);padding-bottom:4px}h3{font-size:1.1rem;margin:0 0 6px}
a{color:var(--accent)}.muted{color:var(--muted)}code{font-size:.9em;background:var(--head);padding:1px 4px;border-radius:4px;word-break:break-word}
.box,.taste{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 16px;margin:14px 0}
.rule{font-weight:600;margin:4px 0 8px}dl{margin:0}dt{font-weight:600;margin-top:10px;color:var(--muted);font-size:.92em}dd{margin:2px 0 0}
blockquote{margin:6px 0;padding:6px 10px;background:var(--quote);border-left:3px solid var(--accent);border-radius:4px}
.badge{display:inline-block;background:var(--warn-bg);color:var(--warn-fg);font-size:.8em;padding:1px 8px;border-radius:10px;font-weight:600;vertical-align:middle}
.guess{background:var(--warn-bg);color:var(--text);padding:8px 10px;border-radius:6px}
.table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--border);border-radius:8px;background:var(--surface);margin:10px 0}
table{border-collapse:collapse;min-width:720px;width:100%;font-size:.93em}th,td{text-align:left;vertical-align:top;padding:7px 10px;border-bottom:1px solid var(--border)}th{background:var(--head);position:sticky;top:0}
.kind{font-size:.82em;padding:1px 7px;border-radius:10px;white-space:nowrap}.kВ{background:var(--kV)}.kП{background:var(--kP)}.kФ{background:var(--kF);border:1px solid var(--border)}
ol.prio li{margin:4px 0}.q h3{margin-top:4px}.opt{margin:4px 0}
"""

N_REL = len(RELAY); N_OTH = len(others)
page = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Вкус: черновик</title><style>{CSS}</style></head>
<body><main>
<h1>Вкус relay — черновик</h1>
<p><b>relay</b> — ваша надстройка над Claude Code: она раздаёт работу агентам нужного уровня, охраняет git, ведёт очередь работ и пишет общие правила во все проекты. Эта страница — черновик «вкуса» relay и план, как вкус заменит встроенную память Claude.</p>
<div class="box">
<p><b>Что такое вкус здесь.</b> Правила говорят, <i>что</i> делать. Вкус говорит, <i>что хорошо и что идёт первым</i>: у каждого раздела есть сигнал (момент, когда он срабатывает), действие и ваши слова как доказательство. Так вкус работает как «signal source, switcher, decider» из вашей первой формулировки 23.10. Трата — один из разделов, как вы поправили 24.10.</p>
<p><b>Память Claude</b> (auto-memory) — заметки, которые Claude Code сам пишет в <code>~/.claude/projects/&lt;папка&gt;/memory/</code> посреди сессии и сам подгружает в следующие сессии той же папки. Она живёт вне relay, на одной машине, без проверки формата.</p>
<p><b>Как ответить:</b> напишите номер раздела и что не так, например «3 — не так, я имел в виду …»; если всё верно — «всё так». Вопросы внизу (раздел 4 страницы) — отдельно, по буквам.</p>
</div>

<div class="box"><p><b>Где выбор, данный мне, слаб (сказано один раз, дальше строю как решено).</b></p>
<ol>
<li><b>«Заменить память, чтобы relay был переносимым».</b> relay сам стоит на Claude Code (крючки, агенты, CLAUDE.md), поэтому переносимость — между машинами, а не между инструментами. Между машинами память можно перенести и без кода: в установленном Claude Code (2.1.309) есть настройка <code>autoMemoryDirectory</code> — папку памяти можно указать внутри репозитория relay. Настоящий выигрыш замены в другом: один источник вместо двух. Сейчас они расходятся: две из 13 заметок relay сами пишут «queued in relay» и «пример в правиле устарел». Цена замены — нужен новый путь записи, иначе каждое новое решение ждёт ветку, рецензию и платный прогон (~$9). Этот путь описан в разделе 3.</li>
<li><b>«Разделы — из прошлых решений владельца».</b> Из 71 решения на странице решений около 33 — одни буквы («1a 2a»): их смысл держится на текстах вопросов, а не на ваших словах. Поэтому вкус из одних этих решений получился бы тонким. Я добавил принципы из заметок других проектов (ALIX, arsenal, SIGHT, общие); у каждого раздела указано, откуда он.</li>
</ol></div>

<h2>1. Разделы вкуса</h2>
<p>9 разделов. Пометка <span class="badge">предположение</span> — меньше двух ваших решений в основании. Целых разделов с ней нет; одно правило внутри раздела 9 помечено. Номера «№ N» — строки страницы решений (21–23.10).</p>
{''.join(sec_html(s) for s in SECTIONS)}

<h2>2. Память Claude → relay</h2>
<p>В {len(glob.glob(ROOT + '/*/memory'))} папках памяти лежат {len(files)} заметок (не считая файлов-оглавлений MEMORY.md); заметки есть в {len(folders)} папках, остальные пусты; без копий из рабочих папок веток — {len(seen)} разных заметок: {N_REL} у relay и {N_OTH} в других проектах. Вид: <span class="kind kВ">вкус</span> — как решать; <span class="kind kП">правило</span> — уже есть в правилах relay или станет строкой в них; <span class="kind kФ">факт</span> — знание о владельце, машине или проекте, не вкус.</p>
<div class="box"><p><b>Факты — не вкус.</b> Оплата (подписка с лимитами), замер цен (relay на 36% ниже /cost 21.10), родной язык, юрисдикция — это сведения, а не способ решать. Они идут туда, где relay уже хранит сведения о владельце: ключ в <code>projects.toml [global]</code>, который <code>relay sync</code> превращает в одну строку общих инструкций (так уже сделано с родным языком: <code>native_language = "Russian"</code> → «My native language: Russian.»). Замеры и история — в документы relay. Сведения о машине (VPN, DNS) — в заметки о машине в документах relay. Состояние и решения конкретного проекта — в документы этого проекта.</p></div>
<h3>Память relay (все {N_REL})</h3>
<p class="muted">Куда: {fmt_cnt(relay_cnt)}.</p>
<div class="table-wrap"><table><thead><tr><th>Заметка</th><th>Вид</th><th>Куда в relay</th><th>Почему</th></tr></thead><tbody>
{relay_rows}
</tbody></table></div>
<h3>Память других проектов ({N_OTH}, без повторов)</h3>
<p class="muted">Куда: {fmt_cnt(other_cnt)}. Под именем — проект(ы), где заметка лежит.</p>
<div class="table-wrap"><table><thead><tr><th>Заметка</th><th>Вид</th><th>Куда</th><th>Почему</th></tr></thead><tbody>
{other_rows}
</tbody></table></div>

<h2>3. Как relay запоминает новое без памяти Claude</h2>
<div class="box">
<p><b>Сейчас.</b> Заметка памяти пишется сразу, посреди сессии, без кода и без проверки. Изменение правила relay — отдельная ветка, рецензия и платный прогон (последний — $8.61, 37 минут). Если просто выключить память, каждое ваше новое предпочтение ждало бы такого цикла: за 21–24.10 появилось 13 заметок, около 3 в день, то есть около $27 в день только на прогоны.</p>
<p><b>Предлагаемый путь: запись решения.</b> Одна команда relay (скажем, <code>relay decide</code>) пишет ваше решение отдельным файлом в <code>.relay/decisions/</code> репозитория relay. Поля: дата, ваши слова дословно (на языке оригинала), где действует (всё или один проект), вид (вкус / факт / указание), раздел вкуса, если есть, и <code>folded_at</code> — дата, когда решение вошло в правило. Поля «состояние» нет: «ещё не вошло» — это просто отсутствие <code>folded_at</code> (раздел 3 вкуса).</p>
<ul>
<li><b>Как попадает в главную ветку.</b> Тем же путём, что запись очереди: если меняется только файл в <code>.relay/decisions/</code>, код сливает его сразу, без рецензии и прогона. Цена одного решения — один коммит, секунды.</li>
<li><b>Как его видит следующая сессия.</b> <code>relay sync</code> (команда тоже запускает его сама) дописывает в созданные relay инструкции раздел «Решения, ещё не вошедшие в правила»: общие — в <code>~/.claude/CLAUDE.md</code>, проектные — в <code>CLAUDE.local.md</code> проекта. Это тот же путь, которым relay уже доставляет правила и родной язык (<code>render_target</code>), — без крючков и без памяти Claude.</li>
<li><b>Как оно становится вкусом.</b> Когда записей без <code>folded_at</code> накапливается много, ведущая сессия предлагает одну ветку «вписать решения в правила»: одна рецензия, один платный прогон на пачку, а не на каждое. Настройка <code>decisions_unfolded_max</code>: по умолчанию 15, предел 30. На пределе общие инструкции вырастают примерно на 3 тыс. токенов в начале каждой сессии во всех проектах, а решения работают без проверки прогоном дольше.</li>
<li><b>Чем проверяется «только одна команда пишет».</b> Крючок отказывает в любой другой записи в <code>.relay/decisions/</code>, как сейчас с меткой проверки, плюс тест на это. Если тест сломан, запись мимо команды пройдёт молча.</li>
<li><b>Связь с очередью.</b> Задача «состояние из фактов» (IP 80) уже просит «дословный датированный журнал ваших решений». Эта запись — её первая половина; сделав её сейчас, мы не строим два журнала.</li>
</ul>
<p><b>Цена.</b> Одно небольшое изменение: команда, схема, раздел в <code>relay sync</code>, исключение для слияния. По замерам 21.10 полный цикл занимает около 30–45 минут агентов, плюс один платный прогон, около $9.</p>
<p><b>Что теряется.</b> (1) Память Claude модель пишет сама, когда сочтёт нужным; здесь она должна вызвать команду. Правило ведущей сессии назовёт момент: вы сказали принцип, предпочтение, поправку или факт о себе. Риск — забыть; дешёвая страховка — после слияния ведущая сессия сверяет ваши дословные слова из журнала передачи с записями. (2) Решение, записанное посреди сессии, попадает в инструкции только следующих сессий; в текущей оно уже есть в разговоре. (3) Запись — коммит в relay; это и выигрыш: видно в истории, переносится с репозиторием.</p>
<p><b>Как выключить память Claude.</b> В установленном Claude Code 2.1.309 есть настройка <code>autoMemoryEnabled</code> («When false, Claude will not read from or write to the auto-memory directory») для <code>settings.json</code> (общий <code>~/.claude/settings.json</code> или проектный <code>.claude/settings.json</code>) и переменная окружения <code>CLAUDE_CODE_DISABLE_AUTO_MEMORY</code>. Я видел их в строках самой программы, а не в документации: <b>надо проверить</b> в живой сессии, что после выключения заметки не подгружаются. relay может сам ставить эту настройку при <code>relay sync</code>, когда придёт время (вопрос 2).</p>
</div>
<div class="table-wrap"><table><thead><tr><th>Путь</th><th>Цена одного решения</th><th>Цена постройки</th><th>Переносимость</th><th>Проверка формата</th><th>Что теряется</th></tr></thead><tbody>
<tr><td><b>А. Запись решения в relay</b></td><td>1 коммит, секунды</td><td>~30–45 мин агентов + ~$9</td><td>с репозиторием relay, любая машина</td><td>схема, одна команда</td><td>модель должна вызвать команду</td></tr>
<tr><td>Б. Папку памяти Claude перенести в relay (<code>autoMemoryDirectory</code>)</td><td>0</td><td>одна настройка</td><td>с репозиторием, но только Claude Code</td><td>нет</td><td>два источника остаются; проза вперемешку: факты, вкус, состояние</td></tr>
<tr><td>В. Без записи: каждое решение — сразу в правило</td><td>ветка + рецензия + ~$9</td><td>0</td><td>полная</td><td>рецензия</td><td>~$27 в день при 3 решениях в день; решение ждёт часы</td></tr>
</tbody></table></div>

<h2>4. Вопросы владельцу</h2>
<section class="box q">
<h3>Вопрос 1. Как relay запоминает ваши новые решения</h3>
<p>Сейчас каждое ваше предпочтение Claude сам записывает в свою память, и она подгружается в следующих сессиях. Это бесплатно и сразу, но живёт вне relay, и две из 13 заметок relay уже расходятся с правилами. Если выключить память, нужен другой путь записи. Пример: 24.10 вы сказали о полях status. Это попало в память Claude и в журнал передачи, но не в правила: правило о данных до сих пор об этом молчит. Путь А пишет такую фразу файлом в relay за секунды и показывает её всем следующим сессиям; путь Б оставляет память Claude, только хранит её в репозитории relay; путь В вписывает каждое решение прямо в правило (ветка, рецензия, ~$9). Таблица выше сравнивает их.</p>
<p class="opt"><b>а)</b> Запись решения в relay (А), вписывать в правила пачками. <i>Рекомендую.</i></p>
<p class="opt"><b>б)</b> Перенести папку памяти Claude в репозиторий relay (Б).</p>
<p class="opt"><b>в)</b> Каждое решение сразу в правило (В).</p>
</section>
<section class="box q">
<h3>Вопрос 2. Сколько памяти переносить и когда её выключать</h3>
<p>Кроме 13 заметок relay, есть {N_OTH} заметок в других проектах (ALIX, arsenal, Glonass, Glyph и др.). Из них {other_cnt.get('вкус',0)} — ваши общие принципы для разделов вкуса и {other_cnt.get('правило',0)} — строки правил relay (большинство уже есть), {other_cnt.get('удалить',0)} устарели, остальные {other_cnt.get('документы проекта',0)+other_cnt.get('[global]',0)} — сведения и состояние конкретного проекта. Например, «les-12990-status» описывает, где стоит задача Glonass на 22.10. Выключатель <code>autoMemoryEnabled</code> можно поставить на всю машину или на один проект. Если выключить память на всей машине сразу, ALIX, Glonass и другие проекты потеряют свои заметки о состоянии до того, как те переедут в документы проектов. Вы также говорили «don't touch» о старых проектах (22.10), а перенос во все проекты — это правки в их репозиториях.</p>
<div class="table-wrap"><table><thead><tr><th></th><th>Что переносится сейчас</th><th>Когда выключить память</th><th>Риск</th></tr></thead><tbody>
<tr><td>а</td><td>13 заметок relay + {other_cnt.get('вкус',0)} принципов во вкус и {other_cnt.get('правило',0)} строк правил; сведения проекта — в его документы, когда в проекте снова идёт работа</td><td>в relay — сразу после пути записи; на всей машине — когда в проекте нет непереехавших заметок</td><td>две системы живут бок о бок неделями</td></tr>
<tr><td>б</td><td>все {len(seen)} заметок сейчас, по агенту на проект</td><td>сразу на всей машине</td><td>правки в старых проектах, которые вы просили не трогать; ~13 проектов работы</td></tr>
<tr><td>в</td><td>только 13 заметок relay</td><td>только в relay</td><td>общие принципы из ALIX и arsenal не попадают во вкус</td></tr>
</tbody></table></div>
<p class="opt"><b>а)</b> Принципы — сейчас, сведения проектов — по мере работы в них. <i>Рекомендую.</i></p>
<p class="opt"><b>б)</b> Всё сразу и выключить везде.</p>
<p class="opt"><b>в)</b> Только relay.</p>
</section>
<section class="box q">
<h3>Вопрос 3. Где действует вкус</h3>
<p>Сейчас правило вкуса подгружается только в сессиях relay: в <code>projects.toml</code> общий набор пропускает его (<code>skip = ["taste"]</code>). Это эксперимент: после 5 слияний я спрошу, оставлять ли его (сейчас 4 из 5). Чтобы вкус заменил память Claude, он должен действовать везде, где вы работаете: принцип «выводимое не хранится» нужен в ALIX так же, как в relay. Цена — текст в начале каждой сессии каждого проекта: девять разделов в сжатом виде правила — около 650 слов, примерно 900 токенов (сейчас правило — 272 слова). Цитаты и примеры с этой страницы в правило не входят, они остаются в документах.</p>
<p class="opt"><b>а)</b> Везде — после проверки эксперимента на 5-м слиянии, если вы его оставите. <i>Рекомендую.</i></p>
<p class="opt"><b>б)</b> Везде — сразу, вместе с новым текстом.</p>
<p class="opt"><b>в)</b> Только relay; в других проектах остаётся память Claude.</p>
</section>
<p class="muted">Черновик собран 24.10 из журнала передачи relay, страницы решений (71 решение 21–23.10), решений 24.10 и {len(files)} файлов памяти Claude. Само правило будет построено позже, отдельным изменением.</p>
</main></body></html>
"""
open(OUT, "w", encoding="utf-8").write(page)
print("sections", len(SECTIONS), "guess", sum(s["guess"] for s in SECTIONS), "subguess", sum(1 for s in SECTIONS if s.get("sub")))
print("relay", N_REL, relay_cnt); print("other", N_OTH, other_cnt); print("files", len(files), "folders", len(folders), "distinct", len(seen))
