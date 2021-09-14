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

DEPS = [
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/step',
    'recipe_engine/path',
    'recipe_engine/raw_io',
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
# TODO(b/189226376): Change tag from 'swiftr' codename to something with
#  an intrinsic meaning.
_INFO_UPREV_TAG = 'swiftr:chrome-uprev-dry-run'

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
    public_src_revision = api.gitiles.fetch_revision(
        'chromium', 'chromium/src', 'main',
        test_output_data={'branch': {
            'revision': 'publicsrc9012revision'
        }})
    rev_info = '# chrome-internal rev: %s\n' \
               '# chromium rev: %s\n' \
               '# chromium/src rev: %s' % (
                 internal_revision, public_revision, public_src_revision)

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
          '\n\n%s\n\nCq-Cl-Tag: %s\nCq-Cl-Tag: chromium_src_ref:%s' % (
            rev_info, _INFO_UPREV_TAG, public_src_revision)
      api.git.commit(message, files=[_CHROMEOS_CHROME_EBUILD_PATH])

    with api.step.nest('upload CL and trigger CQ dry run') as step:
      api.git_cl.upload(reviewers=_UPREV_CL_REVIEWERS, dry_run=True,
                        hashtags=[_INFO_UPREV_TAG])

      gerrit_change_url = api.git_cl.status(
          field='url', fast=True, step_test_data=functools.partial(
              api.raw_io.test_api.stream_output,
              'crrev.com/c/%s' % _FAKE_GERRIT_CHANGE_ID))
      step.links['uprev CL'] = gerrit_change_url


def GenTests(api):
  yield api.test('basic')
