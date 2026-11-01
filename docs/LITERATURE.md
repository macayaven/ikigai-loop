# What the literature supports here, and what it doesn't

The papers below ground design choices and evaluation methods. None of them shows that this product works, and no effect size in them transfers to it. A run with one person and about 7 real choices can describe failures, labels, responses to set perturbations and prediction losses. It can't show behavioural benefit, stable preferences, persistence or generalization, and it can't guarantee truth or privacy.

GPT Sol 6.1, through Codex, checked every citation against primary text on Nov 1, 2026. Claude Code then re-read the 15 marked ✓ itself, from the abstract or full text. The others rest on Sol's check. Every quote comes from the source.

## The problem

| Source | What it says | What I take from it | What it doesn't show |
|---|---|---|---|
| Webb & Sheeran 2006, *Psychol Bull* 132(2):249-268, [doi:10.1037/0033-2909.132.2.249](https://doi.org/10.1037/0033-2909.132.2.249) ✓ | "a medium-to-large change in intention (d = 0.66) leads to a small-to-medium change in behavior (d = 0.36)" | Wanting something more moves behaviour less | Anything about this product's effect |
| Sheeran & Webb 2016, *Soc Personal Psychol Compass* 10(9):503-518, [manuscript](https://eprints.whiterose.ac.uk/id/eprint/107519/3/The%20Intention-Behavior%20Gap%20R1.pdf) | "people do not always do the things that they intend to do" | The problem I'm pointing at | That my mechanism closes the gap |
| Emmons & King 1988, *JPSP* 54(6):1040-1048, [doi:10.1037/0022-3514.54.6.1040](https://doi.org/10.1037/0022-3514.54.6.1040) ✓ | "Subjects were less likely to act on conflictful and ambivalent strivings" | Why two goals competing for one hour is worth looking at | That a two-option card helps |
| Kelly, Mansell & Wood 2015, *Pers Individ Differ* 85:212-229, [doi:10.1016/j.paid.2015.05.011](https://doi.org/10.1016/j.paid.2015.05.011) | "goal conflict, ambivalence and discrepancy impede well-being" | Goal conflict motivates this untested design | Any well-being claim, and I make none |

## The design

| Source | What it says | What I take from it | What it doesn't show |
|---|---|---|---|
| Gollwitzer & Sheeran 2006, *Adv Exp Soc Psychol* 38:69-119, [doi:10.1016/S0065-2601(06)38002-1](https://doi.org/10.1016/S0065-2601%2806%2938002-1); Sheeran, Listrom & Gollwitzer 2025, *Eur Rev Soc Psychol* 36(1):162-194, [doi:10.1080/10463283.2024.2334563](https://doi.org/10.1080/10463283.2024.2334563) | 94 independent tests, d = .65; 642 tests, .27 ≤ d ≤ .66 | A commitment with a specific time reads like an action plan | These are if-then plans people form themselves. An agent offering a slot isn't one |
| Nahum-Shani et al. 2018, *Ann Behav Med* 52(6):446-462, [PMC5364076](https://pmc.ncbi.nlm.nih.gov/articles/PMC5364076/) | "A decision point is a time at which an intervention decision is made" | Vocabulary for what each cycle logs | That my tailoring rules are right |
| Klasnja et al. 2019, *Ann Behav Med* 53(6):573-582, [PMC6401341](https://pmc.ncbi.nlm.nih.gov/articles/PMC6401341/) ✓ | 44 recruited, 37 analysed; a suggestion's effect "was no longer distinguishable from zero by the 28th day" | Prompts can fade, so three days prove nothing about lasting | Any benchmark for me; different outcome, different population |
| Klasnja et al. 2015, *Health Psychol* 34(Suppl):1220-1228, [manuscript](https://archive.md2k.org/images/papers/jitai/nihms732638_Klasnja.pdf) | "enable causal modeling of proximal effects of the randomized intervention components" | The design for a continuation, after the hackathon | Anything about this run, which isn't randomized |
| Harkin et al. 2016, *Psychol Bull* 142(2):198-229, [doi:10.1037/bul0000025](https://doi.org/10.1037/bul0000025) ✓ | 138 studies, N = 19,951, d+ = 0.40; larger "when the information was physically recorded" | Why the ledger records what happens | A tap records acceptance, which isn't monitoring a completed behaviour |
| Michie et al. 2013, *Ann Behav Med* 46(1):81-95, [doi:10.1007/s12160-013-9486-6](https://doi.org/10.1007/s12160-013-9486-6) ✓ | "93 BCTs clustered into 16 groups" | Candidate labels: 1.4 action planning, 1.9 commitment, 2.2 feedback on behaviour, 2.3 self-monitoring, 7.1 prompts/cues | These are my own candidate codings, not checked by a trained coder |
| Ryan & Deci 2000, *Am Psychol* 55(1):68-78, [doi:10.1037/0003-066X.55.1.68](https://doi.org/10.1037/0003-066X.55.1.68) ✓ | Three needs: "competence, autonomy, and relatedness" | Why the commitments are mine and I can always refuse | That this card supports autonomy |
| Locke & Latham 2002, *Am Psychol* 57(9):705-717, [doi:10.1037/0003-066X.57.9.705](https://doi.org/10.1037/0003-066X.57.9.705) | "Goal specificity in itself does not necessarily lead to high performance" | Commitments stated as specific targets is a design choice | Specific wording alone doing anything |

## The evaluation

| Source | What it says | What I take from it | What it doesn't show |
|---|---|---|---|
| Liu, Zhang & Liang 2023, *Findings of EMNLP*, [ACL Anthology](https://aclanthology.org/2023.findings-emnlp.467/) ✓ | "a mere 51.5% of generated sentences are fully supported by citations" and "only 74.5% of citations support their associated sentence", in four generative search engines | Why every number has to reconcile against its cited source | Those rates for other systems |
| Min et al. 2023, *EMNLP*, [ACL Anthology](https://aclanthology.org/2023.emnlp-main.741/) ✓ | "breaks a generation into a series of atomic facts" | R1 rates atomic claims. The gate's parser reconciling a number is a separate thing from a person judging support | That my gate checks truth |
| Turpin et al. 2023, *NeurIPS*, [arXiv:2305.04388](https://arxiv.org/abs/2305.04388) ✓ | "CoT explanations can systematically misrepresent the true reason for a model's prediction" | Why R4 perturbs cited facts instead of trusting a stated reason | That equal rates prove citations are decoration; R4 reports "no differential sensitivity detected" |
| Ribeiro et al. 2020, *ACL*, [ACL Anthology](https://aclanthology.org/2020.acl-main.442.pdf) ✓ | Invariance tests are "perturbations that should not change the output of the model"; directional tests have known expected results | R3 is inspired by these. Its thresholds and expected picks are mine | Generalization past my 20 pairs |
| Nosek et al. 2018, *PNAS* 115(11):2600-2606, [doi:10.1073/pnas.1708274114](https://doi.org/10.1073/pnas.1708274114) ✓ | "define the research questions and analysis plan before observing the research outcomes" | Register first, then log deviations by date | That registering makes a result right. I had also seen synthetic examples before registering |
| Tate et al. 2016 (SCRIBE), *Aphasiology* 30(7):862-876, [doi:10.1080/02687038.2016.1178022](https://doi.org/10.1080/02687038.2016.1178022), [PMC4873717](https://pmc.ncbi.nlm.nih.gov/articles/PMC4873717/), the copy I read; the same statement ran in other journals, such as *Am J Occup Ther* 70(4), [doi:10.5014/ajot.2016.704002](https://doi.org/10.5014/ajot.2016.704002) ✓ | An A-B design "has weak internal validity, there being no control for history or maturation"; "regarded as a quasiexperimental design" | The honest name for my before/during table, and reporting items | Any causal reading of that table |
| Vohra et al. 2015 (CENT), *BMJ* 350:h1738, [BMJ](https://www.bmj.com/content/350/bmj.h1738) | "prospectively planned, multiple crossover trial in a single individual" | Some reporting items | That this is an N-of-1 trial. It has no crossovers |
| Wilson & Collins 2019, *eLife* 8:e49547, [eLife](https://elifesciences.org/articles/49547) ✓ | "First, simulate fake data with known parameter values." | Check the learner can recover a known preference before reading its fit | Recovery on real rulings. Simulations assume a stationary Bernoulli preference |
| Gneiting & Raftery 2007, *JASA* 102(477):359-378, [doi:10.1198/016214506000001437](https://doi.org/10.1198/016214506000001437) ✓ | A strictly proper rule leaves "no incentive to predict any P ≠ Q"; its Example 1 is the "Quadratic or Brier score" | Mean Brier is R8's primary score | That a good score at this n means anything lasting |

## Closest prior work

GPTCoach (Jörke et al., CHI 2025, [doi:10.1145/3706598.3713819](https://doi.org/10.1145/3706598.3713819)) is an LLM physical-activity coach, tested "in a lab study with 16 participants". Haag et al. (CHI 2025, [arXiv:2402.08658](https://arxiv.org/abs/2402.08658) ✓) use LLMs for just-in-time decisions in a rehabilitation scenario, "using three personas" and "450 JITAI decisions and messages": constructed cases, not a patient deployment. Mine differs in target and mechanism: no coaching, only my own commitments, a deterministic gate, and two goals competing. This search wasn't exhaustive.

## About ikigai

The four-circle diagram comes from Marc Winn's 2014 blog post, adapted from Andrés Zuzunaga's purpose diagram, and Winn himself says it isn't the Japanese concept: [his post](https://theviewinside.me/what-is-your-ikigai), [his later note](https://theviewinside.me/what-a-diagram-taught-me-about-organisations-that-have-lost-their-way). That's provenance, not evidence. The measured construct is a different thing, for example Ikigai-9 (Imai et al. 2012, [doi:10.11236/jph.59.7_433](https://doi.org/10.11236/jph.59.7_433)), validated on adults aged 60 and over. `IkigaiWeights` are my preference weights, not that scale.

## What I dropped after the check

- **Sone et al. 2008.** The mortality numbers are right, but they ground nothing here, so I don't cite it for the product.
- **SPEC §5.1's evaluator principles.** That design is retired. AlphaEvolve and the Darwin Gödel Machine use evaluators, but neither establishes that the evaluator is "the bottleneck of any self-improving loop". PoLL's results are for its tested panels. G-Eval and Prometheus don't isolate a general advantage for rubrics. Cohen's κ doesn't validate my old .6 and .7 autonomy cutoffs.

## Claims I relabelled

See the Nov 1 entries under Deviations in [docs/PREREG.md](PREREG.md): the numeric targets are mine, not sourced; "no power" became "no adequately powered comparison was planned"; R4 no longer says citations are decoration.
