# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for syncing remote, distributed tarballs to our local cache."""

DEPS = [
    'recipe_engine/raw_io',
    'cros_dupit',
]

from collections import namedtuple

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

Mirror = namedtuple("Mirror", "uri rate")

# list of of (uri, rate limit) for mirrors to try, in order
MIRRORS = [
    Mirror('rsync://mirror.rackspace.com/gentoo/distfiles', '1m'),
    Mirror('rsync://rsync.gtlib.gatech.edu/gentoo/distfiles', '1m'),
    Mirror('rsync://mirrors.rit.edu/gentoo/distfiles', '1m'),
]

GS_DISTFILES = 'gs://chromeos-mirror/gentoo/distfiles/'


def RunSteps(api):
  for mirror in MIRRORS:
    try:
      api.cros_dupit.configure(
          rsync_mirror_address=mirror.uri,
          rsync_mirror_rate_limit=mirror.rate,
          gs_distfiles_uri='gs://chromeos-mirror/gentoo/distfiles/',
      )
      api.cros_dupit.run()
      break
    except StepFailure:
      continue


def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(
          post_process.MustRun,
          'rsync distfiles from %s' % MIRRORS[0].uri,
      ),
      api.post_process(
          post_process.DoesNotRun,
          'rsync distfiles from %s' % MIRRORS[1].uri,
      ),
  )

  yield api.test(
      'mirror_failure',
      api.step_data(
          'list distfiles in rsync://mirror.rackspace.com/gentoo/distfiles',
          retcode=1,
      ),
      api.post_process(
          post_process.DoesNotRun,
          'rsync distfiles from %s' % MIRRORS[0].uri,
      ),
      api.post_process(
          post_process.MustRun,
          'rsync distfiles from %s' % MIRRORS[1].uri,
      ),
  )
