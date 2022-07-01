# -*- coding: utf-8 -*-

# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf.json_format import MessageToDict
import re

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.cros_source.cros_source import CrosSourceProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import ManifestLocation

CHROMIUM_SRC_PROJECT = 'chromium/src'
CHROMIUM_SRC_URL = 'https://chromium.googlesource.com/{}'.format(
    CHROMIUM_SRC_PROJECT)
LKGM_PATH = 'chromeos/CHROMEOS_LKGM'
LKGM_CL_REVIEWERS = ['chrome-os-gardeners-reviews@google.com']
CI_PROD_SERVICE_ACCOUNT = 'chromeos-ci-prod@chromeos-bot.iam.gserviceaccount.com'
LKGM_HASHTAG = 'chrome-lkgm'

CHROMIUMOS_OVERLAY_PATH = 'src/third_party/chromiumos-overlay'

CHROME_VERSION_REGEXP = r'chromeos-base/chromeos-chrome/chromeos-chrome-\d+\.\d+\.(?P<branch>\d+)\.\d+_.*\.ebuild'

CHROME_EBUILD_TEST_DATA = """
chromeos-base/chromeos-chrome/chromeos-chrome-106.0.5204.0_rc-r1.ebuild
chromeos-base/chromeos-chrome/chromeos-chrome-9999.ebuild
"""


class CrosLkgmApi(recipe_api.RecipeApi):
  """A module to handle the LGKM process and other interactions between the
    Release & Public builders."""

  def __init__(self, properties, *args, **kwargs):
    self._enable_lkgm = properties.enable_lkgm
    self._full_run = properties.full_run
    self._builder_threshold_percentage = properties.builder_threshold_percentage
    self._public_build = None
    self._public_build_results = None
    super(CrosLkgmApi, self).__init__(*args, **kwargs)

  def schedule_public_build(self):
    """Schedules a public build.

    Returns: (common_pb2.Build) The scheduled build.
    """
    with self.m.step.nest('schedule public build'):
      config = self.m.cros_infra_config.config
      if not config:
        raise StepFailure(
            'could not find builder config, needed to determine branch')
      branch = config.orchestrator.gitiles_commit.ref[len('refs/heads/'):]
      # Main release branches build from snapshot manifests.
      if branch in ['snapshot', 'staging-snapshot']:
        branch = 'main'

      is_staging = self.m.cros_infra_config.is_staging
      staging_prefix = 'staging-' if is_staging else ''
      public_orch_name = '{}public-{}-orchestrator'.format(
          staging_prefix, branch)

      buildspec_location = self.m.cros_release.buildspec.manifest_gs_path
      # We want to pass the public buildspec to the public builder.
      buildspec_location = buildspec_location.replace(
          'chromeos-manifest-versions', 'chromiumos-manifest-versions')

      request = self.m.buildbucket.schedule_request(
          bucket='staging' if is_staging else 'release',
          builder=public_orch_name,
          properties={
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_gs_path=buildspec_location))),
          },
          can_outlive_parent=True,
          tags=self.m.buildbucket.tags(
              parent_buildbucket_id=str(self.m.buildbucket.build.id)),
      )
      builds = self.m.buildbucket.schedule([request],
                                           step_name='running public builder')
      self._public_build = builds[0]
      return self._public_build

  def collect_public_build(self):
    """Collects results from the public build.

    Returns: (common_pb2.Build) The scheduled build.
    """
    with self.m.step.nest('collect public orchestrator'):
      if not self._public_build:
        raise StepFailure(
            "collect_public_build called but no public build exists")

      self._public_build_results = self.m.buildbucket.collect_build(
          self._public_build.id, step_name='collect', timeout=60 * 60 * 8)

  def _success_percent(self, builds):
    successful_builds = sum([b.status == common_pb2.SUCCESS for b in builds])
    return successful_builds / float(len(builds)) * 100. if len(builds) else 0

  def do_lkgm(self, release_build_results, use_branch=False):
    """Performs the LGKM process if the build is an LKGM candidate.

    This should only be called from a release orchestrator.

    Args:
      release_build_results (list(common_pb2.Build)): list of release build
        results as returned by api.orch_menu.plan_and_run_children.
      use_branch (bool): if set, upload the LKGM CL to the Chrome branch
        (e.g. refs/branch-heads/5204) instead of ToT.
    """
    if not self._enable_lkgm:
      return
    with self.m.step.nest('assess LKGM readiness') as presentation:
      if not self._is_lkgm_candidate(release_build_results):
        presentation.step_text = 'not an LKGM candidate'
        return
      else:
        presentation.step_text = 'LKGM candidate'
    branch = None
    if use_branch:
      branch = self._get_chrome_branch()

    script_path = self.m.cros_source.workspace_path.join(
        'infra/chromite-HEAD/bin/chrome_chromeos_lkgm')
    cmd = [
        script_path,
        '--lkgm',
        self.m.cros_version.version.platform_version,
        '--buildbucket-id',
        self.m.buildbucket.build.id,
    ]
    if branch:
      cmd.extend(['--branch', 'refs/branch-heads/{}'.format(branch)])
    if not self._full_run:
      cmd.append('--dryrun')
    self.m.step('call chrome_chromeos_lkgm', cmd)

  def _is_lkgm_candidate(self, release_build_results):
    """Determines if the build is an LKGM candidate based on child build results.

    Args:
      release_build_results (list(common_pb2.Build)): list of release builds.

    Returns: (bool) LKGM candidate status.
    """
    with self.m.step.nest('assess release build results') as presentation:
      if not release_build_results:
        presentation.step_text = 'no release builds'
        return False
      success_percent = self._success_percent(release_build_results)
      presentation.step_text = 'release builds have {:.2f}% percent success rate, threshold is {:d}%'.format(
          success_percent, self._builder_threshold_percentage)
      if success_percent < self._builder_threshold_percentage:
        return False

    with self.m.step.nest('assess public build results') as presentation:
      output_props = self._public_build_results.output.properties
      child_build_ids = output_props[
          'child_builds'] if 'child_builds' in output_props else []
      child_builds = self.m.buildbucket.get_multi(
          [int(bbid) for bbid in child_build_ids],
          step_name='get public builders').values() if child_build_ids else []

      if self._public_build_results.status != common_pb2.SUCCESS and not child_builds:
        # If the public orchestrator failed AND there are no child builds, we don't want
        # to consider this version for LKGM.
        presentation.step_text = 'public orchestrator failed and did not report any child builds'
        return False
      else:
        success_percent = self._success_percent(child_builds)
        presentation.step_text = 'public builds have {:.2f}% percent success rate, threshold is {:d}%'.format(
            success_percent, self._builder_threshold_percentage)
        if success_percent < self._builder_threshold_percentage:
          return False
    return True

  def _get_chrome_branch(self):
    """Get the Chrome branch number from the current checkout."""
    with self.m.step.nest('get chrome branch') as presentation:
      with self.m.context(
          self.m.cros_source.workspace_path.join(CHROMIUMOS_OVERLAY_PATH)):
        files = self.m.step(
            'list chrome ebuild files', [
                'stat', '-c', '%n',
                'chromeos-base/chromeos-chrome/chromeos-chrome-*'
            ], stdout=self.m.raw_io.output_text(),
            step_test_data=lambda: self.m.raw_io.test_api.stream_output_text(
                CHROME_EBUILD_TEST_DATA)).stdout.strip().split()
      for f in files:
        match = re.match(CHROME_VERSION_REGEXP, f)
        if match:
          branch = match.groupdict()['branch']
          presentation.step_text = branch
          return branch
      raise StepFailure('could not get chrome branch number')
