## Summary

## Tests

- [ ] `python3 -m unittest discover -s tests -v` with `BITNET_EXECUTABLE` and `BITNET_MODEL` unset
- [ ] BitNet integration test, or not run because no local runtime was configured

## Checks

- [ ] No weights, runtime binaries, credentials, or real candidate banks are added
- [ ] Prompt version and `tests/test_prompt_hash.py` were updated if the template changed
- [ ] `doctor` still withholds `support claimed: yes` unless the installed runtime was verified
