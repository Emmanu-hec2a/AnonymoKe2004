# Avatar preview softness

The preview pipeline now downsamples to 48 x 48, applies a Gaussian blur of 3.5
pixels, and scales with bicubic interpolation to the existing 512 x 512 output.
The previous 24px/8px blur concealed almost all outline; the new preview retains
more outline while suppressing fine detail. Flutter's local onboarding preview
uses the matching intermediate size and blur radius.

Image validation, the single-face gate, orientation normalization, metadata
removal and private-original storage remain in the upload pipeline. Discover
continues to receive a separately generated derivative. Tests cover both the
increase in outline contrast relative to the previous blur and suppression of
fine spatial detail; blur is not a guarantee that a person cannot be recognized.

After deploying both API and worker, existing approved previews can be refreshed:

```sh
python manage.py rebuild_avatar_previews --dry-run --limit 100
python manage.py rebuild_avatar_previews --limit 100
```

The command queues bounded work on the media queue. Each task revalidates the
approved original, locks the active account and asset before publishing, and
checks current privacy/sensitive-data consent. It overwrites only the tracked
derived object. The original object, profile visibility and asset approval state
stay intact. Keeping the same tracked key preserves erasure coverage and avoids
orphaned objects. A failed rebuild leaves the existing approved preview intact.
Existing image caches can retain the previous derivative for up to five minutes.

Four native PostGIS tests exercise approved-only operation, retention of the
private original and paused state, owner deactivation, and consent withdrawal.
They passed in an isolated uniquely named test database that was removed after
the run. No production rows or uploaded images were used in those tests.
