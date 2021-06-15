# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the Chrome uprev builder.

Triggers a passive uprev attempt against current Chrome ToT by generating a CL
that touches chromeos-chrome-9999.ebuild, adding the gardeners as reviewers,
and triggering a CQ dry-run.
"""

import functools
import os

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builds_service as bb_service
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/step',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/time',
    'git',
    'git_cl',
    'gitiles',
]

_BUILDBUCKET_BASE_URL = 'https://ci.chromium.org/b'
_CHROMEOS_GERRIT_HOST = 'chromium-review.googlesource.com'
_CHROMEOS_OVERLAY_PROJECT = 'chromiumos/overlays/chromiumos-overlay'
_CHROMEOS_OVERLAY_REPO = 'https://chromium.googlesource.com/%s' % _CHROMEOS_OVERLAY_PROJECT
_CHROMEOS_CHROME_EBUILD_PATH = 'chromeos-base/chromeos-chrome/chromeos-chrome-9999.ebuild'

_UPREV_CL_REVIEWERS = ['chrome-os-gardeners-reviews@google.com']
_UPREV_CL_TAG = 'chrome-uprev-dry-run'

_FAKE_GERRIT_CHANGE_ID = '12341234'


def RunSteps(api):
  with api.step.nest('get git revision for chromeos-chrome ToT'):
    internal_revision = api.gitiles.fetch_revision(
        'chrome-internal', 'chrome/src-internal', 'main',
        test_output_data={'branch': {
            'revision': 'internal1234revision'
        }})
    public_revision = api.gitiles.fetch_revision(
        'chromium', 'chromium', 'trunk',
        test_output_data={'branch': {
            'revision': 'public5678revision'
        }})
    rev_info = '# chrome-internal rev: %s\n# chromium rev: %s' % (
        internal_revision, public_revision)

  with api.context(cwd=api.path.mkdtemp()):
    with api.step.nest('clone %s' % _CHROMEOS_OVERLAY_PROJECT):
      api.git.clone(_CHROMEOS_OVERLAY_REPO)

    with api.step.nest('modify %s' % _CHROMEOS_CHROME_EBUILD_PATH):
      local_ebuild_path = api.context.cwd.join(_CHROMEOS_CHROME_EBUILD_PATH)
      current_ebuild = api.file.read_text('read file', local_ebuild_path,
                                          test_data='sample file contents')
      modified_ebuild = '%s\n\n%s' % (rev_info, current_ebuild)
      api.file.write_raw('write to file', local_ebuild_path, modified_ebuild)

    with api.step.nest('commit changes'):
      api.git.add([_CHROMEOS_CHROME_EBUILD_PATH])
      message = 'chromeos-chrome uprev dry-run with Chrome ToT' \
          '\n\n%s\n\nCq-Cl-Tag: %s' % (rev_info, _UPREV_CL_TAG)
      api.git.commit(message, files=[_CHROMEOS_CHROME_EBUILD_PATH])

    with api.step.nest('upload CL and trigger CQ dry run') as step:
      api.git_cl.upload(reviewers=_UPREV_CL_REVIEWERS, dry_run=True,
                        hashtags=[_UPREV_CL_TAG])

      gerrit_change_url = api.git_cl.status(
          field='url', fast=True, step_test_data=functools.partial(
              api.raw_io.test_api.stream_output,
              'crrev.com/c/%s' % _FAKE_GERRIT_CHANGE_ID))
      step.links['uprev CL'] = gerrit_change_url

    with api.step.nest('wait for CQ dry-run to start') as step:
      gerrit_change_id = int(
          api.git_cl.status(
              field='id', fast=True, step_test_data=functools.partial(
                  api.raw_io.test_api.stream_output, _FAKE_GERRIT_CHANGE_ID)))

      cq_tryjobs = _tryjobs_for_gerrit_cl(api, gerrit_change_id)
      while not cq_tryjobs:
        api.time.sleep(600)
        cq_tryjobs = _tryjobs_for_gerrit_cl(api, gerrit_change_id)

      cq_run = cq_tryjobs[0]
      step.links['CQ dry-run'] = os.path.join(_BUILDBUCKET_BASE_URL,
                                              str(cq_run.id))

    with api.step.nest('wait for CQ dry-run to finish'):
      while cq_run.status in [bb_common.SCHEDULED, bb_common.STARTED]:
        api.time.sleep(600)
        cq_run = api.buildbucket.get(cq_run.id)


def _tryjobs_for_gerrit_cl(api, cl_id):
  return api.buildbucket.search(
      bb_service.BuildPredicate(
          builder={
              'project': 'chromeos',
              'bucket': 'cq',
              'builder': 'cq-orchestrator',
          }, gerrit_changes=[
              bb_common.GerritChange(
                  change=cl_id,
                  host=_CHROMEOS_GERRIT_HOST,
                  project=_CHROMEOS_OVERLAY_PROJECT,
                  patchset=1,
              )
          ]))


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.simulated_search_results(
          [], step_name='wait for CQ dry-run to start.buildbucket.search'),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(id=99999999, status='SCHEDULED'),
      ], step_name='wait for CQ dry-run to start.buildbucket.search (2)'),
      api.buildbucket.simulated_get(
          build_pb2.Build(id=99999999, status='STARTED'),
          step_name='wait for CQ dry-run to finish.buildbucket.get'),
      api.buildbucket.simulated_get(
          build_pb2.Build(id=99999999, status='SUCCESS'),
          step_name='wait for CQ dry-run to finish.buildbucket.get (2)'))
