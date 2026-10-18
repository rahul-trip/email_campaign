"""Every instruction given to a language model, one module per role.

A prompt module owns WHAT is said; the stage owns when and how it is sent. Convention: a
``*_SYSTEM_PROMPT`` constant plus a ``build_*_user_prompt()`` function.
"""
