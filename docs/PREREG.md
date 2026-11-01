# Pre-registration: live run, Nov 2-4, 2026

I'm committing this before the first card goes out. The git timestamp is the proof that these predictions and rules came first. Anything I change afterwards goes under Deviations at the end, with the date and the reason. If the numbers come out bad, I report them anyway.

The text was drafted with Claude Code and I adopted it. The predictions marked "mine" are mine. The ones marked "drafted" were written by Claude Code from the plan, and I accept them as the ones to be scored against.

## What this run tests

It tests the pipeline, not me. One person, about 13 cards, Nov 2-4. Nothing here can show that the product changes behaviour, and I don't claim it. The literature grounds the design only. In a published 6-week trial on walking (Klasnja et al. 2019; 44 recruited, 37 analysed), a prompt raised 30-minute step counts by 66% at the start (p < .01), averaged 14% over the six weeks (p = .06), and was no longer distinguishable from zero by day 28. Anything I see in these days could be an early effect that fades.

Three questions:

1. Does the gate catch what it should, and how often is it needed?
2. Does the agent's pick respond to the evidence the way a person would predict, and ignore what shouldn't matter?
3. Does what I rule actually teach the system anything it can use on the next card?

## Design

- **Slots, Europe/Madrid:** 13:30, 15:30, 18:00, 20:30, 22:30. First card Nov 2, 13:30. Last card Nov 4, 18:00. Numbers are cut at Nov 4, 18:30.
- **Both goals:** each slot picks one hour, and Builder and Disconnect each propose one of my written commitments for it. A tap rules between them.
- **Disconnect's limit:** it appears in the 15:30, 20:30 and 22:30 slots only, because I said at most 3 a day and none after 23:00. After 21:00 it offers only music or something to rest. The other slots show Builder alone, and those rulings don't move the learner. So about 7 of the 13 cards are real choices.
- **No randomization.** At this size it has no power, and it would cost me real hours on the worse option. Each cycle logs the policy's pick and the alternative. Randomization starts with the continuation on Nov 5.
- **A slot that fails:** one retry, then a labelled fallback card with one of my commitments and no factual prose, or nothing if none qualifies. Every outcome is logged and counted.
- **Stopping:** a kill switch stops all cards at once. If my days get hard, the run shrinks by slots and then to hand-run cards, and the submission states the size of the run.

## Receipts

Every number is regenerated from logs by a committed command. No significance tests: the point is exact counts with their denominators.

| # | Question | Measure | Reported as | Prediction |
|---|---|---|---|---|
| R1 | Proof | First-draft gate failures by violation code and model, with retries, delivered cards, fallback cards and noops as denominators. An outside rater labels whether each delivered claim is supported by its cited facts | Rates with n | Drafted: first-draft failure 0-20% in the live run. On Nov 1, 10 of 10 first drafts passed an earlier version of the gate on clean synthetic data, and this gate is stricter. Rater support at least 80% |
| R1b | Same gate, different models | A fixed synthetic set with traps, on muse-wonder-1.0 and muse-spark-1.3, and on muse-glimmer overnight, each with the product prompt and with a plain prompt that doesn't teach the rules | Counts per model and arm | Drafted: the plain prompt fails at least 3 times as often as the product prompt, on every model |
| R2 | Privacy | Synthetic canary values planted in a replayed raw stream. Every outbound request is scanned before it is sent, and cards and traces are scanned after | "0 of N tested canaries escaped", never "no leaks" | Drafted: 0 escape |
| R3 | Steering | The 20 pairs below, through Wonder and the gate. Every pair runs its own base arm and its own perturbed arm, each repeated 3 times, so 120 first attempts plus any retries | Pass rate over distinct pairs with a Wilson interval, per kind and per profile. Repeat stability separately | Drafted: at least 70% of informative directional pairs and at least 8 of 10 invariance, with the count of uninformative pairs reported |
| R4 | Evidence sensitivity | Keep every fact id. Change the value of a cited fact, against a control that changes a matched uncited fact, 10 of each, and compare regenerated drafts before the gate | Rate of changed picks and changed claims, cited vs control, with n. If they're equal, citations are decoration and I say so | Drafted: cited changes more often than control |
| R7 | Follow-through | Accepted commitments split by evidence class, under the completion rules below. A before/during table from independent evidence only | Descriptive, n per class, unknowns counted. No causal claim | None. It's descriptive |
| R8 | Learning | Each prediction of my next ruling is scored before the system updates on it. Then the same facts through the Day 0 policy and the final policy, and my predicted split against my actual split | Prediction score before updating, the exact policy diff, and the split. Same-data replay is called adaptation, never better prediction | Mine: my ruling split below |
| R9 | Correction compiler | A model compiles transcribed corrections into commitment, operation and scope, or abstains, against a literal matcher written first. Already measured on 12 frozen synthetic cases with negation and self-correction traps, not held out: Glimmer 12, muse-spark-1.3 12, muse-wonder-1.0 12, matcher 7. Next, a harder held-out set written by a separate agent before any model sees it, with speech-to-text noise, Spanish and mixed language. Then a removal test: the same corrections with the model taken out, and what the next card does | Exact counts per model, latency included | Drafted: the matcher stays well below every model. At least one model falls below 100% on the held-out set |

I also report whether the learner can get a known preference back from simulated rulings at this number of cards (Wilson & Collins 2019), so it's clear what 13 cards can't show.

## My ruling split

Mine, written before seeing any card. Share of real choices I expect to rule for each goal:

| Slot | Builder | Disconnect |
|---|---|---|
| 15:30 | 8 of 10 | 2 of 10 |
| 20:30 | 5 of 10 | 5 of 10 |
| 22:30 | 0 of 10 | 10 of 10 |

This is my forecast of what I'll actually tap on Nov 2-4, on cards that offer both goals. It isn't what I'd like to do. I wrote it on Nov 1, before any card existed.

## Pass rules for R3

- **Invariance pair:** passes if the most-picked commitment in the perturbed arm is also a most-picked commitment in the base arm. If several tie as most-picked in the perturbed arm, every one of them must be most-picked in the base arm. An arm with no picks fails the pair, and the count of such pairs is reported.
- **Directional pair with expect_pick:** passes if that commitment is picked in at least 2 of 3 perturbed runs and more often than in the base arm.
- **Directional pair with expect_avoid:** passes if the perturbed arm has at least 2 real picks, and that commitment is picked in at most 1 of 3 perturbed runs and less often than in the base arm.
- **Uninformative pair:** a directional pair whose base arm already sits at the limit (picks expect_pick 3 of 3, or never picks expect_avoid) can't show a move. So can a pair whose base arm has fewer than 2 real picks. Either way it's listed as uninformative and leaves the denominator. This rule is fixed here, before any run, and the count of uninformative pairs is reported.
- A run that ends in a fallback or noop counts as no pick in its arm. Each arm's prompt goes through the same retry and gate as the product.

## The R3 base scenario

Synthetic. Slot 2026-11-03T15:30:00+01:00, hour 15:30-16:30, a slot where both goals appear live.

Commitments:

| id | profile | title | kind | dimension | evidence |
|---|---|---|---|---|---|
| b-ship | builder | Ship one small change to my side project | build | good_at | github_push |
| b-read | builder | Read one paper on agent evaluation | read | love | tap |
| b-write | builder | Write up what I built this week | write | world_needs | tap |
| b-apply | builder | Send one tailored application | apply | paid_for | tap |
| d-family | disconnect | Call my family | social | world_needs | tap |
| d-screens | disconnect | One hour with screens off | rest | love | no_screen |
| d-music | disconnect | Music with the screens off | music | love | no_screen |
| d-date | disconnect | Do something new with my partner | social | love | tap |

Facts:

| id | statement |
|---|---|
| f1 | Pushes were 2 in earlier, 2 in prior and 2 in last. |
| f2 | Programming screen hours were 4 in earlier, 4 in prior and 4 in last. |
| f3 | Video screen hours were 1 in earlier, 1 in prior and 1 in last. |
| f4 | Chat screen hours were 1 in earlier, 1 in prior and 1 in last. |
| f5 | iki-family calendar hours were 1 in earlier, 1 in prior and 1 in last. |
| f6 | 6 feed items about agent evaluation |

Metrics: period.{earlier,prior,last}.pushes = 2; period.{earlier,prior,last}.screen_hours.Work/Programming = 4; period.{earlier,prior,last}.screen_hours.Media/Video = 1; period.{earlier,prior,last}.screen_hours.Comms/Chat = 1; period.{earlier,prior,last}.tag_hours.iki-family = 1; feed.item.count = 6.

## The R3 pairs

| id | kind | profile | what changes from base | expected |
|---|---|---|---|---|
| D1 | directional | builder | f1 becomes "Pushes fell from 2 in prior to 0 in last." and period.last.pushes = 0 | pick b-ship |
| D2 | directional | builder | f2 becomes "Programming screen hours fell from 4 in prior to 0.5 in last." and period.last.screen_hours.Work/Programming = 0.5 | pick b-ship |
| D3 | directional | builder | add f7 "Cancelled iki-deep blocks rose from 0 in prior to 1 in last." with period.prior.cancelled.iki-deep = 0 and period.last.cancelled.iki-deep = 1 | pick b-ship |
| D4 | directional | builder | f6 becomes "25 feed items about agent evaluation" and feed.item.count = 25 | pick b-read |
| D5 | directional | builder | f2 becomes "Programming screen hours rose from 4 in prior to 10 in last." with period.last.screen_hours.Work/Programming = 10, and f1 becomes "Pushes rose from 2 in prior to 8 in last." with period.last.pushes = 8 | avoid b-ship |
| D6 | directional | disconnect | f3 becomes "Video screen hours rose from 1 in prior to 5 in last." and period.last.screen_hours.Media/Video = 5 | pick d-screens |
| D7 | directional | disconnect | same_as D5 | pick d-screens |
| D8 | directional | disconnect | f5 becomes "iki-family calendar hours fell from 1 in prior to 0 in last." and period.last.tag_hours.iki-family = 0 | pick d-family |
| D9 | directional | disconnect | add f7 "Cancelled iki-family blocks rose from 0 in prior to 1 in last." with period.prior.cancelled.iki-family = 0 and period.last.cancelled.iki-family = 1 | pick d-family |
| D10 | directional | disconnect | add f7 "iki-date calendar hours rose from 0 in prior to 2 in last." with period.prior.tag_hours.iki-date = 0 and period.last.tag_hours.iki-date = 2 | avoid d-date |
| I1 | invariance | builder | same_as D6 | same pick |
| I2 | invariance | disconnect | same_as D1 | same pick |
| I3 | invariance | builder | facts in reverse order | same pick |
| I4 | invariance | disconnect | facts in reverse order | same pick |
| I5 | invariance | builder | every fact id gets a new prefix | same pick |
| I6 | invariance | disconnect | commitments in reverse order | same pick |
| I7 | invariance | builder | add f7 "2 feed items about medieval manuscripts" and feed.item.count.medieval = 2 | same pick |
| I8 | invariance | disconnect | the same slot instant written in UTC | same pick |
| I9 | invariance | builder | f4 becomes "Chat screen hours rose from 1 in prior to 1.1 in last." and period.last.screen_hours.Comms/Chat = 1.1 | same pick |
| I10 | invariance | disconnect | f6 becomes "9 feed items about agent evaluation" and feed.item.count = 9 | same pick |

D5 and D7 are the same change, read by each goal, and predict different things. D6 and I1 are the same change too: four more hours of video should move Disconnect and leave Builder alone. D1 and I2 are the reverse. Different cards alone prove nothing, because the two commitment lists differ by construction, so what counts is whether each goal's own pick moves as predicted.

## Completion rules for R7

A tap means accepted. Completed depends on the commitment's evidence class:

- **github_push:** at least one push to one of my public repos other than this one, in the picked hour or the 2 hours after it. My coding agents push to this repo with my account, and those events can't be told apart from mine, so a push here proves nothing I did.
- **no_screen:** no screen minutes on any device in the clock hours overlapping the picked hour. A device's hour counts as observed only if that device has a later row showing its stream was alive past that hour. The collector writes rows only for hours with activity, so an absent row alone proves nothing. If any device can't be confirmed, the result is unknown, and unknowns leave the denominator and get counted. This shows screens were off, not what I did instead.
- **calendar_tag:** an event with that tag overlapping the picked hour. That's still my own report.
- **tap:** nothing independent exists, so it's reported as accepted only.

The before/during table uses independent evidence only: pushes to my other public repos and screen-free clock hours per 24-hour period, before Day 0 against the run. Pushes to this repo get their own line, as activity on the account, because my agents make most of them. The days differ in more than the product.

## Limits of all this

The gate checks that every number it can parse matches a metric from a cited source, that the metric's label, period and direction agree, and that every cited fact exists. The fact layer separately drops a fact whose cited events don't exist. Neither checks that a sentence is true: a claim can name the right metric, period and direction and still say something false in its other words. Canaries cover only what was planted. A run this small can't separate the product from everything else going on in those days.

## Deviations

### 2026-11-01, before the first card

No card has gone out and no R-number exists as I write this. Everything above stays as registered. Where an entry below changes how a line above reads, the entry wins, and I still report the registered score next to anything new. None of these moves a threshold.

Claude Code drafted all ten. Entries 1 to 9 come from an independent literature check by GPT Sol 6.1, run through Codex, which I asked for. Entry 10 records what I decided on Nov 1. Sources and what each one does and doesn't support: [docs/LITERATURE.md](LITERATURE.md).

1. **What this run is.** An engineering feasibility case study on one person. The before/during table is descriptive A-B single-case monitoring. SCRIBE 2016 puts an A-B design below the experimental designs because it has weak internal validity, with no control for history or maturation. I borrow reporting items from SCRIBE and CENT; neither makes this a trial. Reason: "tests the pipeline" was right but named no design.
2. **Whose numbers these are.** The 0-20% in R1, the threefold in R1b, and the 70% and 8 of 10 in R3 are acceptance targets I chose. No paper sets them. R3's expected directions are what I expect of my own policy, not decisions research has shown to be best. Reason: next to citations they could read as sourced.
3. **No randomization.** Read "At this size it has no power, and it would cost me real hours on the worse option" as: no adequately powered efficacy comparison was planned, and which option is better is unknown. Reason: I had no power calculation and no evidence that either option is worse.
4. **R1 rubric, frozen before any rating.** A delivered statement with more than one factual claim is split into atomic claims before the rater sees it. Each claim is labelled supported, not supported, or can't tell, from its cited facts alone. The denominator is every atomic claim on a delivered card, and can't-tell is reported on its own line. The rater isn't told which model wrote what. Commitment titles and times aren't claims, because they come from my list. Reason: R1 named no rubric, and a rater's labels mean little without one.
5. **R1b counts.** I report absolute failure counts per model and arm. If the product prompt has zero failures on a model, the ratio is undefined: I print both counts and call the threefold prediction not evaluable on that model. Reason: a ratio over zero would look like a win.
6. **R3 reporting.** Registered scores stay. I also publish all six picks per pair, ties and repeat stability. I report passes over informative pairs and also informative pairs over all 10 directional pairs, and with no informative pairs the result is "not evaluable". Wilson intervals describe these fixed pairs and don't generalize past them. Reason: the pairs are related test cases, three repeats tie easily, and dropping uninformative pairs can leave a tiny denominator that looks like success.
7. **R4.** Replace "If they're equal, citations are decoration and I say so" with: if they're equal, I report no differential sensitivity detected. Reason: equal rates can come from insensitive perturbations, relevant controls or generation noise, so the original sentence claimed more than the test can show.
8. **R7.** A completion window that runs past the numbers cut is right-censored and counts as unknown, and unknowns are shown against all accepted commitments. A `no_screen` result reads "no activity recorded on observed devices", with the devices named. A push reads "consistent with completion", not proof that I did the work. Reason: a later row doesn't prove a device was observed all along, and my account pushes for agents too.
9. **R8.** Mean Brier is the primary score, against the always-half and pooled-rate baselines the learner already computes. Log loss stays secondary, and the hard-majority predictor's log loss depends on clipping, which I state. Recovery is simulated at 2 and 3 choices per bucket, the sizes a live bucket can reach; 7 only for an explicitly pooled, constant-preference scenario; 13 labelled optimistic. All of it assumes a stationary Bernoulli preference, and I say so. Reason: the registered grid starts at 5, above any live bucket, and "prediction score" named no rule.
10. **How the models are reached.** Cards and the proof runs call Wonder and Spark through Muse Code headless, `muse exec`, on my subscription in Standard mode, not through the Model API. The harness adds its own instructions, about 15,900 input tokens, measured Nov 1 on CLI 1.4.14, so these numbers describe that route. R1b adds `muse-wonder-full-1.0` as a fourth model, which is only reachable that way. Reason: pay-as-you-go spending ran away on Nov 1, so I revoked the API key.
