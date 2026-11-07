# Responsible use

voiceover-studio clones a voice from a short recording. That is useful for narrating your own videos, and harmful
if used to imitate someone else. This page explains what the tool is for and what it is not for.

## Permitted

- Voiceovers in **your own voice** for your own videos, courses, demos and presentations.
- A voice whose owner has **given you explicit permission**, recorded through the consent step.
- The synthetic demo voice shipped in `samples/` (it belongs to no real person).

## Not permitted

- Cloning anyone's voice without their explicit consent, including public figures, colleagues, family or friends.
- Impersonation, fraud, scams, or bypassing voice-based authentication.
- Political or electoral deception, fake news, fabricated statements, or harassment.
- Sexual or intimate content, or content about minors.
- Removing or weakening the watermark or the AI-generated label to pass synthetic audio off as real.

## Safeguards built into the core

These are part of the core code, not configuration switches:

1. **Consent recording.** Cloning requires a recording of the speaker reading a consent sentence. Speech-to-text
   checks that the recording matches the sentence. The recording is stored as the consent record.
2. **Watermark.** Every output carries an inaudible [AudioSeal](https://github.com/facebookresearch/audioseal)
   watermark, whatever model produced it.
3. **Label.** Every file carries an "AI-generated voice" provenance label in its metadata.
4. **Script checks.** Requests to write scripts that impersonate named real people are refused.
5. **Private by design.** No public endpoint: the UI is reached only through an encrypted AWS Session Manager tunnel.

A watermark can be detected by anyone with the open detector, and a determined attacker may be able to weaken it.
It helps, but it is not proof against misuse. Your judgement is the main safeguard.

## Tell your audience

Disclose that the voice is AI-generated. Several platforms require it (e.g. YouTube's altered or synthetic content
disclosure), and laws increasingly do too (e.g. the EU AI Act's transparency rules, India's 2026 IT Rules on
synthetically generated content). This is not legal advice: check the rules where you publish.

## Your data

Voice recordings are personal, possibly biometric, data. With the default (local) providers they stay in your own
AWS account. You can delete them from the UI at any time, and `destroy.sh` removes everything. If you choose a
hosted provider, your voice sample is sent to that vendor under their terms. The UI warns you before that happens.

## Reporting misuse

If you find this project being used to harm someone, or a way to bypass its safeguards, see [SECURITY.md](SECURITY.md).
