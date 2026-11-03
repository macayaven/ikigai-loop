# R9 through audio, in my cloned voice and Meta speech-to-text

I ran my R9 voice correction set through sound, not text. A Claude Code agent ran the evaluation. I write up what I did and what I found.

## What I measured

R9 is my frozen set of 60 voice edits. I had each one spoken once in my own cloned voice, with Chatterbox (MIT), run locally from my recording, with my consent. I transcribed each take with Meta speech-to-text through the product's own transcriber (`framework/voice/transcribe.py`). I then compiled each transcript with R9's own runner and the default arm (muse-spark-1.3, minimal effort). I also ran the text arm in the same session as the baseline, on the frozen transcripts as written.

## Result

| Slice | n | STT WER | WER, accents folded | Exact transcripts | Audio arm | Text arm (today) | Published default | Matcher on text | Matcher on STT |
|---|---|---|---|---|---|---|---|---|---|
| en | 30 | 10.2% | 10.2% | 11/30 | 27/30 | 29/30 | 29/30 | 5/30 | 5/30 |
| es | 15 | 14.5% | 13.4% | 3/15 | 13/15 | 14/15 | 14/15 | 2/15 | 2/15 |
| mixed | 15 | 25.0% | 23.8% | 1/15 | 10/15 | 15/15 | 15/15 | 6/15 | 5/15 |
| overall | 60 | 14.8% | 14.3% | 15/60 | 50/60 | 58/60 | 58/60 | 13/60 | 12/60 |

| Paired (audio vs text, today) | en | es | mixed | overall |
|---|---|---|---|---|
| right in both | 27 | 13 | 10 | 50 |
| right only from audio | 0 | 0 | 0 | 0 |
| right only from text | 2 | 1 | 5 | 8 |
| wrong in both | 1 | 1 | 0 | 2 |
| exact McNemar p (two-sided) | 0.5 | 1.0 | 0.0625 | 0.0078 |

I got 50 of 60 from audio against 58 of 60 from text.

Every audio miss compiled to no change with a question, so no wrong edit came from audio, but each miss costs me a round trip.

Mixed-language notes lost the most.

## Every audio miss

| id | language | original | what STT heard | WER | audio compiled | text compiled | accepted |
|---|---|---|---|---|---|---|---|
| 105 | mixed | The paper esta noche, after dinner. | The buffer esta noche after dinner. | 17% | none + question | defer/p1/today | defer/p1/today |
| 112 | mixed | o sea skip el right up hoy estoy muerto | and write up Hoy estoy muerto. | 56% | none + question | skip/w1/today | skip/w1/today |
| 113 | en | push the date to friday | push the day to Friday. | 20% | none + question | defer/d1/this_week | defer/d1/this_week |
| 114 | en | Take the paper out for now. We'll see, I might bring it back. | Take the paper out for now. We'll see I might bring it back. | 0% | none + question | none + question | skip/p1/open |
| 129 | mixed | i can't not do the wind down esta noche my sleep's a mess | nando the wind down esta noche my sleep's a mess. | 31% | none + question | keep/n1 | keep/n1 |
| 131 | en | I'm not seeing anyone new, take the date off the list. | I'm not seeing anyone new take the date off the list | 0% | none + question | drop/d1/open | drop/d1/open |
| 137 | mixed | move the date al viernes no wait mañana mejor | Move it no way mañana mejor | 56% | none + question | defer/d1/tomorrow | defer/d1/tomorrow |
| 145 | es | La cita sigue en pie, no la toques. | La siesta sigue en pie no la toques. | 12% | none + question | keep/d1 | keep/d1 |
| 156 | mixed | Ya hice el draft this morning, lo mandé y todo. | Jay said dropped this morning, lo mandé y todo. | 40% | none + question | done/w1/today | done/w1/today |
| 157 | es | Deja el borrador hasta el lunes. | The herringwarador hasta el lunes. | 50% | none + question | skip/w1/this_week | defer/w1/tomorrow or skip/w1/today |

Cases 114 and 157 miss in both arms, as in the published run.

## The TTS confound and the Whisper check

A mispronounced word and a misheard word look the same in my results, and no person listened to the takes. I used Whisper-medium as a second recogniser to separate the two, not as ground truth. Whisper has its own biases, and it never fed the compile step.

| Diagnostic | en | es | mixed | overall |
|---|---|---|---|---|
| TTS takes flagged broken | 0 | 0 | 0 | 0 |
| Meta STT WER | 10.2% | 14.5% | 25.0% | 14.8% |
| Whisper-medium WER (diagnostic) | 7.3% | 6.4% | 22.1% | 10.6% |
| Meta STT inexact, Whisper exact | 6 | 6 | 1 | 13 |
| both inexact | 13 | 6 | 13 | 32 |
| Meta STT exact, Whisper inexact | 3 | 1 | 0 | 4 |

## Limits

- Synthetic speech in my cloned voice is not me speaking. The takes are clean and even, with no room noise, no phone microphone, and no Telegram codec.
- I used one take per case, one transcription per take from a non-deterministic STT, and one compile pass per arm.
- I spoke all mixed notes with `language_id="es"`.
- R9 transcripts already hold simulated mishearings, so a real recogniser sits on top of a simulated one here.
- Only the overall difference is significant. The per-language McNemar p values do not pass.
- The case attributions and the observations in the source came after I saw the results.

## Where the data is

The per-case rows and the summaries are in `evals/r9_audio/results.json`. The audio stays private, because it is my cloned voice.

The scripts ran privately, outside the repo. They did this, step by step: spoke each frozen transcript once in my cloned voice; transcribed each take with the product's own transcriber; built a copy of the frozen case file with only each transcript replaced by its transcription, checked field by field against the frozen file; ran both arms through the repo's own runner (`evals/r9.py`, through its `cases_path` and `results_dir` arguments), with the literal matcher on both; and scored the runs with R9's strict scorer and a WER script with fixed rules. The method can be repeated with the repo's own runner.
