"""Unified data-exchange seam (S46.0).

Generic, vocabulary-free import/export infrastructure: a registry, an
``EntityExchanger`` port, the VBWD-standard envelope (JSON + CSV + ZIP bundle),
a generic ``BaseModelExchanger``, and the admin routes. Core ships only the
seam; plugins (and S46.1 core exchangers) register their own exchangers at
enable-time via DI — core never names a plugin domain.
"""
