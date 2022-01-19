# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for syncing Archlinux to our local cache for Borealis VM image."""

DEPS = [
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_dupit',
]

from collections import namedtuple

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

Mirror = namedtuple("Mirror", "uri rate")

# list of of (uri, rate limit) for mirrors to try, in order
MIRRORS = [
    Mirror('rsync://ord.mirror.rackspace.com/archlinux/', '50m'),
    Mirror('rsync://mirrors.kernel.org/archlinux/', '50m'),
    Mirror('rsync://arch.mirror.constant.com/archlinux/', '50m'),
    Mirror('rsync://mirror.sfo12.us.leaseweb.net/archlinux/', '50m'),
    Mirror('rsync://dfw.mirror.rackspace.com/archlinux/', '50m'),
    Mirror('rsync://mirrors.rit.edu/archlinux/', '50m'),
]

GS_DISTFILES = 'gs://chromeos-mirror/archlinux/'


def RunSteps(api):
  mirror_success = False
  for mirror in MIRRORS:
    with api.step.nest('mirror from {}'.format(mirror.uri)) as duplicate:
      try:
        api.cros_dupit.configure(
            rsync_mirror_address=mirror.uri,
            rsync_mirror_rate_limit=mirror.rate,
            gs_distfiles_uri='gs://chromeos-mirror/archlinux/',
        )
        api.cros_dupit.run()
        mirror_success = True
        break
      except StepFailure:
        duplicate.step_text = 'mirroring of {} failed'.format(mirror.uri)
        duplicate.status = api.step.WARNING
        continue
  if not mirror_success:
    raise StepFailure('all mirrors failed')


def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(
          post_process.MustRun,
          'mirror from %s.rsync distfiles from %s' %
          (MIRRORS[0].uri, MIRRORS[0].uri),
      ),
      api.post_process(
          post_process.DoesNotRun,
          'mirror from %s.rsync distfiles from %s' %
          (MIRRORS[1].uri, MIRRORS[1].uri),
      ),
      api.post_process(post_process.StatusSuccess),
  )

  yield api.test(
      'mirror_failure',
      api.step_data(
          'mirror from %s.list distfiles in %s' %
          (MIRRORS[0].uri, MIRRORS[0].uri),
          retcode=1,
      ),
      api.post_process(
          post_process.DoesNotRun,
          'mirror from %s.rsync distfiles from %s' %
          (MIRRORS[0].uri, MIRRORS[0].uri),
      ),
      api.post_process(
          post_process.MustRun,
          'mirror from %s.rsync distfiles from %s' %
          (MIRRORS[1].uri, MIRRORS[1].uri),
      ),
      api.post_process(post_process.StatusSuccess),
  )

  yield api.test(
      'all_mirror_failure',
      api.step_data(
          'mirror from %s.list distfiles in %s' %
          (MIRRORS[0].uri, MIRRORS[0].uri),
          retcode=1,
      ),
      api.step_data(
          'mirror from %s.list distfiles in %s' %
          (MIRRORS[1].uri, MIRRORS[1].uri),
          retcode=1,
      ),
      api.step_data(
          'mirror from %s.list distfiles in %s' %
          (MIRRORS[2].uri, MIRRORS[2].uri),
          retcode=1,
      ),
      api.step_data(
          'mirror from %s.list distfiles in %s' %
          (MIRRORS[3].uri, MIRRORS[3].uri),
          retcode=1,
      ),
      api.step_data(
          'mirror from %s.list distfiles in %s' %
          (MIRRORS[4].uri, MIRRORS[4].uri),
          retcode=1,
      ),
      api.step_data(
          'mirror from %s.list distfiles in %s' %
          (MIRRORS[5].uri, MIRRORS[5].uri),
          retcode=1,
      ),
      api.post_process(
          post_process.DoesNotRun,
          'mirror from %s.rsync distfiles from %s' %
          (MIRRORS[0].uri, MIRRORS[0].uri),
      ),
      api.post_process(
          post_process.DoesNotRun,
          'mirror from %s.rsync distfiles from %s' %
          (MIRRORS[1].uri, MIRRORS[1].uri),
      ),
      api.post_process(
          post_process.DoesNotRun,
          'mirror from %s.rsync distfiles from %s' %
          (MIRRORS[2].uri, MIRRORS[2].uri),
      ),
      api.post_process(
          post_process.DoesNotRun,
          'mirror from %s.rsync distfiles from %s' %
          (MIRRORS[3].uri, MIRRORS[3].uri),
      ),
      api.post_process(
          post_process.DoesNotRun,
          'mirror from %s.rsync distfiles from %s' %
          (MIRRORS[4].uri, MIRRORS[4].uri),
      ),
      api.post_process(
          post_process.DoesNotRun,
          'mirror from %s.rsync distfiles from %s' %
          (MIRRORS[5].uri, MIRRORS[5].uri),
      ),
      api.post_process(post_process.StatusFailure),
  )
