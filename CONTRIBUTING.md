# Contributing

Keep the distinction between the author, the AI, and the controller explicit. Changes must preserve author review and the default planning-only mode.

Before opening a pull request:

```sh
python3 -m unittest discover -s tests -v
```

Use a small synthetic project when reporting a problem. Include the command, expected behavior, actual behavior, Python version, and operating system. Mark fictional approval records as test fixtures. Do not include a real manuscript, private result, personal path, credential, or runtime state.

Keep `SKILL.md` short. Put deterministic requirements in the controller or configuration. Add tests for meaningful behavior and state transitions, rather than checking the wording of a prompt.

Specialist skills remain optional and separately licensed. Add a capability binding or a scoped task interface rather than embedding another skill's entire instructions. Avoid introducing a new runtime dependency when the standard library can do the job.

Explain the problem and resulting behavior in the pull request, with the checks actually performed. Record limitations without claiming untested scientific or writing-quality improvements.
