# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import Chroot
from PB.chromiumos.common import Profile
from PB.recipe_modules.chromeos.cros_prebuilts.cros_prebuilts import CrosPrebuiltsProperties
from PB.recipe_modules.chromeos.cros_prebuilts.examples.full import FullProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import CrosSourceProperties
from recipe_engine.post_process import DoesNotRun
from recipe_engine.post_process import MustRun
from recipe_engine.post_process import StepException

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_infra_config',
    'cros_prebuilts',
    'git',
    'src_state',
    'test_util',
]


PROPERTIES = FullProperties


def RunSteps(api, properties):
  api.cros_infra_config.configure_builder()

  if properties.overridden_builder_config != BuilderConfig.Id.TYPE_UNSPECIFIED:
    builder_config = properties.overridden_builder_config
  else:
    builder_config = BuilderConfig.Id.POSTSUBMIT
  api.cros_prebuilts.upload_target_prebuilts(properties.build_target,
                                             properties.sysroot,
                                             properties.chroot,
                                             properties.profile, builder_config,
                                             properties.gs_bucket,
                                             properties.private)


def GenTests(api):

  def test_data(private=False, use_staging=False, send_snapshot_prebuilts=4,
                commit_overlay_binhost=True, profile=None, dirty_source=False,
                max_binhost_uris=1, overridden_builder_config=None):
    gs_bucket = 'staging-prebuilt-bucket' if use_staging else 'prebuilt-bucket'
    target = 'amd64-generic'

    non_base_profile = (profile and profile.name and profile.name != 'base')
    expect_commit = (
        commit_overlay_binhost and not non_base_profile and not dirty_source)

    ret = api.test_util.test_child_build(target, cq=False).build
    build_target = BuildTarget(name=target)
    test_props = FullProperties(
        build_target=build_target, sysroot=Sysroot(build_target=build_target),
        chroot=Chroot(path='/path/to/chroot',
                      out_path='/path/to/out'), private=private,
        gs_bucket=gs_bucket, profile=profile, dirty_source=dirty_source,
        overridden_builder_config=overridden_builder_config)

    ret += api.properties(test_props)

    props = {
        '$chromeos/cros_prebuilts':
            CrosPrebuiltsProperties(
                use_staging_branch=use_staging,
                send_snapshot_prebuilts=send_snapshot_prebuilts,
                commit_overlay_binhost=commit_overlay_binhost,
                max_binhost_uris=max_binhost_uris)
    }

    # Forcing cros_source to claim dirty source.
    if dirty_source:
      props['$chromeos/cros_source'] = CrosSourceProperties(
          snapshot_cas=CrosSourceProperties.SnapshotCas(digest='xxx'))

    ret += api.properties(**props)

    check = MustRun if expect_commit else DoesNotRun
    ret += api.post_check(check, 'upload prebuilts.update binhost conf file')
    if expect_commit:
      ret += api.step_data(
          'upload prebuilts.update binhost conf file.create change.'
          'update ref.gerrit transaction.diff check.git diff', retcode=1)
    return ret

  for private in False, True:
    for use_staging in False, True:
      for send_snapshot_prebuilts in 0, 1:
        name = '%s%s%s' % (
            'staging-' if use_staging else '',
            'private' if private else 'public',
            '-send' if send_snapshot_prebuilts else '',
        )
        yield api.test(
            name, test_data(private, use_staging, send_snapshot_prebuilts),
            api.post_check(
                MustRun,
                'upload prebuilts.update binhost conf file.create change'
                '.update ref.gerrit transaction'),
            api.step_data(
                ('upload prebuilts.update binhost conf file.create change'
                 '.update ref.gerrit transaction.git push'),
                stderr=api.raw_io.output_text(
                    ('remote:   https://chromium-review.googlesource'
                     '.com/c/chromiumos/infra/recipes/+/123 git_txn: test'))))

  yield api.test(
      'update-retry-exhaustion',
      test_data(),
      api.step_data(
          'upload prebuilts.update binhost conf file.create change.'
          'update ref.gerrit transaction.diff check.git diff', retcode=1),
      api.step_data(
          'upload prebuilts.update binhost conf file.create change (2).'
          'update ref.gerrit transaction.diff check.git diff', retcode=1),
      api.step_data(
          'upload prebuilts.update binhost conf file.create change (3).'
          'update ref.gerrit transaction.diff check.git diff', retcode=1),
      api.step_data(
          'upload prebuilts.update binhost conf file.create change (4).'
          'update ref.gerrit transaction.diff check.git diff', retcode=1),
      api.post_check(StepException,
                     'upload prebuilts.update binhost conf file'),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'update-retry-not-called', test_data(),
      api.step_data(
          ('upload prebuilts.update binhost conf file.create change.update ref'
           '.gerrit transaction.git push'), stderr=api.raw_io.output_text(
               ('remote:   https://chromium-review.googlesource'
                '.com/c/chromiumos/infra/recipes/+/123 git_txn: test'))),
      api.post_check(
          DoesNotRun,
          'upload prebuilts.update binhost conf file.create change' +
          '.update ref (2)'))

  yield api.test('disable-overlay-commits',
                 test_data(commit_overlay_binhost=False))

  yield api.test(
      'with-profile',
      test_data(profile=Profile(name='generic_build'), max_binhost_uris=2))

  # Ensure neither CQ nor POSTSUBMIT build types is supported.
  yield api.test(
      'release-build-type',
      test_data(
          profile=Profile(name='generic_build'),
          overridden_builder_config=BuilderConfig.Id.RELEASE),
      api.expect_exception('ValueError'),
      status='INFRA_FAILURE',
  )

  # This test forces dirty source and thus tests the code path of
  # upload_target_prebuilts skipping binhost commit and metadata
  # upload.
  yield api.test('dirty-source', test_data(dirty_source=True))
