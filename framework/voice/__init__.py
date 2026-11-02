"""Ticket 14: voice correction.

A voice note in the Telegram chat is stored before anything can lose it,
transcribed on the Muse Code subscription, compiled into one typed operation
by a guarded model call, checked by code, applied as append-only events, and
answered in the chat. This package holds the compile prompt and its schema;
later steps add state, transcription, the ledger, and the worker.
"""
