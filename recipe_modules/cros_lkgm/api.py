# -*- coding: utf-8 -*-

# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf.json_format import MessageToDict

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.cros_source.cros_source import CrosSourceProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import ManifestLocation

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

CHROMIUM_SRC_PROJECT = 'chromium/src'
CHROMIUM_SRC_URL = 'https://chromium.googlesource.com/{}'.format(
    CHROMIUM_SRC_PROJECT)
LKGM_PATH = 'chromeos/CHROMEOS_LKGM'
LKGM_CL_REVIEWERS = ['chrome-os-gardeners-reviews@google.com']
CI_PROD_SERVICE_ACCOUNT = 'chromeos-ci-prod@chromeos-bot.iam.gserviceaccount.com'
LKGM_HASHTAG = 'chrome-lkgm'

CHROMIUMOS_OVERLAY_PATH = 'src/third_party/chromiumos-overlay'

CHROME_VERSION_REGEXP = r'chromeos-base/chromeos-chrome/chromeos-chrome-\d+\.\d+\.(?P<branch>\d+)\.\d+_.*\.ebuild'

CHROME_EBUILD_TEST_DATA = '''
chromeos-base/chromeos-chrome/chromeos-chrome-106.0.5204.0_rc-r1.ebuild
chromeos-base/chromeos-chrome/chromeos-chrome-9999.ebuild
'''



class CrosLkgmApi(recipe_api.RecipeApi):
  """A module to handle the LGKM process and other interactions between the
    Release & Public builders."""

  def __init__(self, properties, *args, **kwargs):
    self._enable_lkgm = properties.enable_lkgm
    self._full_run = properties.full_run
    self._builder_threshold_percentage = properties.builder_threshold_percentage
    self._public_build = None
    self._public_build_results = None
    super().__init__(*args, **kwargs)

  @property
  def has_public_build(self):
    """Check if a public build was scheduled."""
    return self._public_build is not None

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
          bucket='staging' if is_staging else 'chromiumos',
          builder=public_orch_name,
          properties={
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_gs_path=buildspec_location),
                          use_external_source_cache=True)),
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
            'collect_public_build called but no public build exists')

      #TODO: Bring down the collect timeout after investigation. b/304094706
      self._public_build_results = self.m.buildbucket.collect_build(
          self._public_build.id, step_name='collect', timeout=60 * 60 * 13)

  def _success_build_count(self, builds):
    return sum([b.status == common_pb2.SUCCESS for b in builds])

  def _success_percent(self, builds):
    successful_builds = self._success_build_count(builds)
    return successful_builds / float(len(builds)) * 100. if len(builds) else 0

  def _build_result_text(self, builds):
    successful_builds = self._success_build_count(builds)
    total_builds = len(builds)
    success_percent = self._success_percent(builds)
    return '{:.2f}% ({:d} of {:d}) builds succeeded, threshold: {:d}%'.format(
        success_percent, successful_builds, total_builds,
        self._builder_threshold_percentage)

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
      presentation.step_text = 'LKGM candidate'

    branch = None
    if use_branch:
      milestone = self.m.cros_version.version.milestone
      branch = self.m.cros_schedule.get_chrome_branch(milestone)
      if branch is None:
        step_text = (
            f"A branch corresponding to M{milestone} doesn't exist on the " +
            'chromium repo yet. This usually happens when the OS-side ' +
            'branching is done earlier than the browser-side branching.')
        self.m.step.empty("skipping uprev: chromium branch doesn't exist",
                          step_text=step_text)
        return

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

  def cleanup_cls(self):
    """Performs the LGKM cleaning-up process.

    This does only the cleaning-up process of LKGM CLs, in contrast that
    `do_lkgm` does the actual uprev process as well.
    """
    with self.m.step.nest('clean up LKGM CLs') as presentation:
      if not self._enable_lkgm:
        presentation.step_text = 'LKGM is not enabled. Do nothing.'
        return

      script_path = self.m.cros_source.workspace_path.join(
          'infra/chromite-HEAD/bin/chrome_chromeos_lkgm')
      cmd = [
          script_path,
          '--buildbucket-id',
          self.m.buildbucket.build.id,
      ]
      if not self._full_run:
        cmd.append('--dryrun')
      self.m.step('call chrome_chromeos_lkgm', cmd)

  def _is_lkgm_candidate(self, release_build_results):
    """Determines if the build is an LKGM candidate based on child build results.

    Args:
      release_build_results (list(common_pb2.Build)): list of release builds.

    Returns: (bool) LKGM candidate status.
    """
    result = True

    with self.m.step.nest('assess release build results') as presentation:
      if not release_build_results:
        presentation.step_text = 'no release builds'
        result = False
      else:
        success_percent = self._success_percent(release_build_results)
        presentation.step_text = \
            'release builds: ' + self._build_result_text(release_build_results)
        if success_percent < self._builder_threshold_percentage:
          result = False

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
        result = False
      elif not child_builds:
        presentation.step_text = 'no public builds'
        result = False
      else:
        success_percent = self._success_percent(child_builds)
        presentation.step_text = \
            'public builds: ' + self._build_result_text(child_builds)
        if success_percent < self._builder_threshold_percentage:
          result = False

    return result
