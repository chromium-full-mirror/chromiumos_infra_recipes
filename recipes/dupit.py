# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for syncing remote, distributed tarballs to our local cache."""

from typing import Generator

from PB.recipes.chromeos.dupit import DupitProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_dupit',
]


PROPERTIES = DupitProperties


def RunSteps(api: RecipeApi, properties: DupitProperties) -> None:
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
            gs_distfiles_uri=properties.gs_uri,
            ignore_missing_args=properties.ignore_missing_args,
            filter_missing_links=properties.filter_missing_links,
            regex_for_archival_sync=properties.regex_for_archival_sync,
            gs_uri_for_archival_sync=properties.gs_uri_for_archival_sync,
            path_datetime_for_archival_sync=properties
            .path_datetime_for_archival_sync,
            gs_topdir_backfill=properties.gs_topdir_backfill,
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


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
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
      'gs_uri': 'gs://chromeos-mirror-test/gentoo/distfiles/',
      'ignore_missing_args': False,
      'filter_missing_links': False,
  }
  arch_props = {
      'mirrors': [
          {
              'uri': 'rsync://arch.mirror.constant.com/archlinux/',
              'rate': '50m',
          },
          {
              'uri': 'rsync://mirror.sfo12.us.leaseweb.net/archlinux/',
              'rate': '50m',
          },
      ],
      'gs_uri':
          'gs://chromeos-mirror-test/archlinux/',
      'ignore_missing_args':
          True,
      'filter_missing_links':
          True,
      'regex_for_archival_sync':
          '^.+[.](db|db.tar.gz|files|files.tar.gz)$',
      'gs_uri_for_archival_sync':
          'gs://chromeos-mirror/archlinux-archive/repos/',
      'path_datetime_for_archival_sync':
          '%Y/%m/%d/%H%M%S%f/',
  }

  props = good_props.copy()
  yield api.test(
      'basic',
      api.step_data(
          'mirror from rsync://mirrors.rit.edu/gentoo/distfiles.copy new distfiles to gs.list new distfiles',
          stdout=api.raw_io.output_text('new_distfile.tar.gz')),
      api.properties(**props),
      api.post_process(
          post_process.MustRun,
          ('mirror from rsync://mirrors.rit.edu/gentoo/distfiles.'
           'gsutil list distfiles in gs://chromeos-mirror-test/gentoo/distfiles/'
          ),
      ),
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
      api.post_process(
          post_process.MustRun,
          ('mirror from rsync://mirrors.rit.edu/gentoo/distfiles.copy'
           ' new distfiles to gs.gsutil upload new distfiles to gs://'
           'chromeos-mirror-test/gentoo/distfiles/')),
      api.post_process(
          post_process.DoesNotRun,
          ('mirror from rsync://mirrors.rit.edu/gentoo/distfiles.'
           'copy new distfiles to gs.gsutil upload additional regex files'
           ' to gs://chromeos-mirror-test/gentoo/distfiles/')),
  )

  yield api.test(
      'basic-arch',
      api.step_data(
          'mirror from rsync://arch.mirror.constant.com/archlinux/.copy new distfiles to gs.list new distfiles',
          stdout=api.raw_io.output_text('new_distfile.tar.gz')),
      api.properties(**arch_props),
      api.post_process(
          post_process.MustRun,
          ('mirror from rsync://arch.mirror.constant.com/archlinux/.'
           'gsutil list distfiles in gs://chromeos-mirror-test/archlinux/'),
      ),
      api.post_process(
          post_process.MustRun,
          ('mirror from rsync://arch.mirror.constant.com/archlinux/.'
           'copy new distfiles to gs.gsutil upload additional regex files'
           ' to gs://chromeos-mirror-test/archlinux/'),
      ),
      api.post_process(
          post_process.MustRun,
          ('mirror from rsync://arch.mirror.constant.com/archlinux/.'
           'rsync distfiles from rsync://arch.mirror.constant.com/archlinux/'),
      ),
      api.post_process(
          post_process.DoesNotRun,
          ('mirror from rsync://mirror.sfo12.us.leaseweb.net/archlinux/.'
           'rsync distfiles from rsync://mirror.sfo12.us.leaseweb.net/archlinux/'
          ),
      ),
  )

  yield api.test(
      'mirror-failure',
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
  )

  yield api.test(
      'all-mirror-failure',
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
      status='FAILURE',
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
      status='FAILURE',
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
      status='FAILURE',
  )
