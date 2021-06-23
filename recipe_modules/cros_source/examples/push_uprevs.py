# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/properties',
    'cros_source',
    'repo',
]
from PB.chromite.api.packages import UprevPackagesResponse

from PB.recipe_modules.chromeos.cros_source.examples.push_uprevs import (
    PushUprevsArgs)

from recipe_engine import post_process

PROPERTIES = PushUprevsArgs


def RunSteps(api, properties):
  # Create temp path
  temp_dir = api.path.mkdtemp()

  # Init Repo
  api.repo.init('http://manifest_url')

  # Create ebuild file
  ebuild_path = api.path.join(temp_dir, 'test.ebuild')
  api.path.mock_add_paths(ebuild_path)
  uprev_response = UprevPackagesResponse(
      modified_ebuilds=[UprevPackagesResponse.Ebuild(path=ebuild_path)],
      version='123.456.789.0')

  uprev_info = []
  for ebuild in uprev_response.modified_ebuilds:
    uprev_info.append(
        api.cros_source.PushUprevRequest(
            ebuild.path,
            'cros_source: uprev test subject',
        ))

  api.cros_source.push_uprev(
      uprev_info,
      True,
      commit_only=properties.commit_only,
      is_staging=properties.is_staging,
  )


def GenTests(api):
  yield api.cros_source.test(
      'commit-only',
      api.properties(PushUprevsArgs(commit_only=True, is_staging=True)),
      api.post_check(post_process.MustRun, 'push uprevs.commit uprevs'),
      api.post_check(post_process.MustRunRE,
                     r'.*commit uprevs.commit uprev changes in.*'),
      api.post_check(post_process.MustRunRE, r'.*git commit$'),
  )

  yield api.cros_source.test(
      'push-uprevs-prod',
      api.properties(PushUprevsArgs(
          commit_only=False,
          is_staging=False,
      )),
      api.post_check(post_process.MustRunRE,
                     r'.*commit uprevs.commit uprev changes in.*'),
      api.post_check(post_process.MustRunRE, r'.*git commit$'),
      api.post_check(post_process.MustRunRE, r'^push uprevs.push to.*'),
      api.post_check(post_process.MustRunRE, r'.*.git push.*'),
      api.post_check(
          post_process.StepCommandContains,
          'push uprevs.push to ../tmp_tmp_1.git push ../tmp_tmp_1',
          'HEAD:refs/heads/main',
      ),
      api.post_check(
          post_process.LogContains,
          'push uprevs',
          'Passed Uprevs',
          ['../tmp_tmp_1'],
      ),
  )

  yield api.cros_source.test(
      'push-uprevs-staging',
      api.properties(PushUprevsArgs(
          commit_only=False,
          is_staging=True,
      )),
      api.post_check(post_process.MustRun, 'push uprevs.commit uprevs'),
      api.post_check(post_process.MustRunRE,
                     r'.*commit uprevs.commit uprev changes in.*'),
      api.post_check(post_process.MustRunRE, r'.*git commit$'),
      api.post_check(post_process.MustRun, 'push uprevs'),
      api.post_check(post_process.MustRunRE, r'^push uprevs.push to.*'),
      api.post_check(post_process.MustRunRE, r'.*.git push.*'),
      api.post_check(
          post_process.StepCommandContains,
          'push uprevs.push to ../tmp_tmp_1.git push ../tmp_tmp_1',
          'HEAD:refs/heads/staging-infra-main',
      ),
      api.post_check(
          post_process.LogContains,
          'push uprevs',
          'Passed Uprevs',
          ['../tmp_tmp_1'],
      ),
  )

  yield api.cros_source.test(
      'push-uprevs-retry-no-change',
      api.properties(PushUprevsArgs(
          commit_only=False,
          is_staging=False,
      )),
      api.step_data(
          'push uprevs.push to ../tmp_tmp_1.git push ../tmp_tmp_1',
          retcode=1,
          stdout=api.raw_io.output(
              ' ! [remote rejected]   HEAD -> main (no new changes)'),
      ),
      api.post_check(post_process.LogEquals, 'push uprevs', 'Passed Uprevs',
                     ''),
  )

  yield api.cros_source.test(
      'push-uprevs-retry-fetch-first',
      api.properties(PushUprevsArgs(
          commit_only=False,
          is_staging=False,
      )),
      api.step_data(
          'push uprevs.push to ../tmp_tmp_1.git push ../tmp_tmp_1',
          retcode=1,
          stdout=api.raw_io.output(
              '!	HEAD:refs/heads/main	[rejected] (fetch first)'),
      ),
      api.post_check(post_process.LogEquals, 'push uprevs', 'Passed Uprevs',
                     '../tmp_tmp_1'),
  )
  yield api.cros_source.test(
      'push-uprevs-retry-fetch-first-staging',
      api.properties(PushUprevsArgs(
          commit_only=False,
          is_staging=True,
      )),
      api.step_data(
          'push uprevs.push to ../tmp_tmp_1.git push ../tmp_tmp_1',
          retcode=1,
          stdout=api.raw_io.output(
              '!	HEAD:refs/heads/main	[rejected] (fetch first)'),
      ),
      api.post_check(post_process.LogEquals, 'push uprevs', 'Passed Uprevs',
                     '../tmp_tmp_1'),
  )

  yield api.cros_source.test(
      'push-uprevs-retry-fast-forward',
      api.properties(PushUprevsArgs(
          commit_only=False,
          is_staging=False,
      )),
      api.step_data(
          'push uprevs.push to ../tmp_tmp_1.git push ../tmp_tmp_1',
          retcode=1,
          stdout=api.raw_io.output(
              '!	HEAD:refs/heads/main	[rejected] (non-fast-forward)'),
      ),
      api.post_check(post_process.LogEquals, 'push uprevs', 'Passed Uprevs',
                     '../tmp_tmp_1'),
  )
  yield api.cros_source.test(
      'push-uprevs-retry-unknown',
      api.properties(PushUprevsArgs(
          commit_only=False,
          is_staging=False,
      )),
      api.step_data(
          'push uprevs.push to ../tmp_tmp_1.git push ../tmp_tmp_1',
          retcode=1,
      ),
      api.post_check(post_process.LogEquals, 'push uprevs', 'Passed Uprevs',
                     ''),
  )

  yield api.cros_source.test(
      'push-uprevs-retry-fail',
      api.properties(PushUprevsArgs(
          commit_only=False,
          is_staging=False,
      )),
      api.step_data(
          'push uprevs.push to ../tmp_tmp_1.git push ../tmp_tmp_1',
          retcode=1,
          stdout=api.raw_io.output(
              '!	HEAD:refs/heads/main	[rejected] (non-fast-forward)'),
      ),
      api.step_data(
          ('push uprevs.push to ../tmp_tmp_1.retry uprev to '
           '../tmp_tmp_1.git push ../tmp_tmp_1'),
          retcode=1,
          stdout=api.raw_io.output(
              '!	HEAD:refs/heads/main	[rejected] (non-fast-forward)'),
      ),
      api.step_data(
          ('push uprevs.push to ../tmp_tmp_1.retry uprev to ../tmp_tmp_1.'
           'git push ../tmp_tmp_1 (2)'),
          retcode=1,
          stdout=api.raw_io.output(
              '!	HEAD:refs/heads/main	[rejected] (non-fast-forward)'),
      ),
      api.step_data(
          ('push uprevs.push to ../tmp_tmp_1.retry uprev to ../tmp_tmp_1.'
           'git push ../tmp_tmp_1 (3)'),
          retcode=1,
          stdout=api.raw_io.output(
              '!	HEAD:refs/heads/main	[rejected] (non-fast-forward)'),
      ),
      api.post_check(post_process.LogEquals, 'push uprevs', 'Passed Uprevs',
                     ''),
  )
