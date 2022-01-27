# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for syncing remote, distributed tarballs to our local cache."""

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_dupit',
]

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

from PB.recipes.chromeos.dupit import DupitProperties

PROPERTIES = DupitProperties


def RunSteps(api, properties):
  with api.step.nest('validate properties'):
    if not properties.mirrors:
      raise StepFailure('must set mirrors')
    if not properties.gs_uri:
      raise StepFailure('must set gs_uri')

  mirror_success = False
  for mirror in properties.mirrors:
    with api.step.nest('mirror from {}'.format(mirror.uri)) as duplicate:
      try:
        api.cros_dupit.configure(
            rsync_mirror_address=mirror.uri,
            rsync_mirror_rate_limit=mirror.rate,
            gs_distfiles_uri='gs://chromeos-mirror/gentoo/distfiles/',
            ignore_missing_args=properties.ignore_missing_args,
            filter_missing_links=properties.filter_missing_links,
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
  good_props = {
      'mirrors': [
          {
              'uri': 'rsync://mirrors.rit.edu/gentoo/distfiles',
              'rate': '1m',
          },
          {
              'uri': 'rsync://mirror.rackspace.com/gentoo/distfiles',
              'rate': '1m',
          },
      ],
      'gs_uri': 'gs://chromeos-mirror/gentoo/distfiles/',
      'ignore_missing_args': False,
      'filter_missing_links': False,
  }

  props = good_props.copy()
  yield api.test(
      'basic',
      api.properties(**props),
      api.post_process(
          post_process.MustRun,
          ('mirror from rsync://mirrors.rit.edu/gentoo/distfiles.'
           'rsync distfiles from rsync://mirrors.rit.edu/gentoo/distfiles'),
      ),
      api.post_process(
          post_process.DoesNotRun,
          ('mirror from rsync://mirror.rackspace.com/gentoo/distfiles.'
           'rsync distfiles from rsync://mirror.rackspace.com/gentoo/distfiles'
          ),
      ),
      api.post_process(post_process.StatusSuccess),
  )

  yield api.test(
      'mirror_failure',
      api.properties(**props),
      api.step_data(
          ('mirror from rsync://mirrors.rit.edu/gentoo/distfiles.'
           'list distfiles in rsync://mirrors.rit.edu/gentoo/distfiles'),
          retcode=1,
      ),
      api.post_process(
          post_process.DoesNotRun,
          ('mirror from rsync://mirrors.rit.edu/gentoo/distfiles.'
           'rsync distfiles from rsync://mirrors.rit.edu/gentoo/distfiles'),
      ),
      api.post_process(
          post_process.MustRun,
          ('mirror from rsync://mirror.rackspace.com/gentoo/distfiles.'
           'rsync distfiles from rsync://mirror.rackspace.com/gentoo/distfiles'
          ),
      ),
      api.post_process(post_process.StatusSuccess),
  )

  yield api.test(
      'all_mirror_failure',
      api.properties(**props),
      api.step_data(
          ('mirror from rsync://mirrors.rit.edu/gentoo/distfiles.'
           'list distfiles in rsync://mirrors.rit.edu/gentoo/distfiles'),
          retcode=1,
      ),
      api.step_data(
          ('mirror from rsync://mirror.rackspace.com/gentoo/distfiles.'
           'list distfiles in rsync://mirror.rackspace.com/gentoo/distfiles'),
          retcode=1,
      ),
      api.post_process(
          post_process.DoesNotRun,
          ('mirror from rsync://mirrors.rit.edu/gentoo/distfiles.'
           'rsync distfiles from rsync://mirrors.rit.edu/gentoo/distfiles'),
      ),
      api.post_process(
          post_process.DoesNotRun,
          ('mirror from rsync://mirror.rackspace.com/gentoo/distfiles.'
           'rsync distfiles from rsync://mirror.rackspace.com/gentoo/distfiles'
          ),
      ),
      api.post_process(post_process.StatusFailure),
  )

  props = good_props.copy()
  del props['mirrors']
  yield api.test(
      'no-mirrors',
      api.properties(**props),
      api.post_process(
          post_process.DoesNotRun,
          ('mirror from rsync://mirrors.rit.edu/gentoo/distfiles.'
           'list distfiles in rsync://mirrors.rit.edu/gentoo/distfiles'),
      ),
      api.post_check(post_process.StatusAnyFailure),
      api.post_check(post_process.StatusFailure),
  )

  props = good_props.copy()
  del props['gs_uri']
  yield api.test(
      'no-gs-uri',
      api.properties(**props),
      api.post_process(
          post_process.DoesNotRun,
          ('mirror from rsync://mirrors.rit.edu/gentoo/distfiles.'
           'list distfiles in rsync://mirrors.rit.edu/gentoo/distfiles'),
      ),
      api.post_check(post_process.StatusAnyFailure),
      api.post_check(post_process.StatusFailure),
  )
