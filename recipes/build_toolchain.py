# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Builds and uploads the CrOS toolchain."""

import os
import re
from typing import Any
from typing import Dict
from typing import Generator

from PB.chromite.api.sdk import BuildPrebuiltsRequest
from PB.chromite.api.sdk import BuildSdkTarballRequest
from PB.chromite.api.sdk import BuildSdkToolchainRequest
from PB.chromite.api.sdk import CreateBinhostCLsRequest
from PB.chromite.api.sdk import CreateManifestFromSdkRequest
from PB.chromite.api.sdk import UploadPrebuiltPackagesRequest
from PB.chromiumos import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipes.chromeos.build_toolchain import BuildToolchainProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'build_menu',
    'cros_build_api',
    'cros_sdk',
    'cros_version',
    'gerrit',
    'repo',
    'test_util',
    'workspace_util',
]

PROPERTIES = BuildToolchainProperties

PYTHON_VERSION_COMPATIBILITY = 'PY3'

# The 'board' that represents the host platform the SDK will be run on.
SDK_BUILD_TARGET = 'amd64-host'

SDK_TARBALL_SUFFIX = '.tar.xz'

# Prebuilts are uploaded to a path that contains
# f"{VERSION_PREFIX}-{sdk_version}". If you change this, make sure all
# consumers are changed as well; see b/303300440.
VERSION_PREFIX = 'chroot'


def _insert_before_change_id(change: str, description: str, text: str) -> str:
  """Insert text before the Change-Id in a change's description.

  This effectively inserts text in description and returns the
  result, but with some tests and reporting that is factored
  into this function instead of being repeated at the point
  of use.

  Args:
    change: identifier for the change (shown in diagnostics)

    description: the original change description text

    text: text to insert

  Returns:
    the new description text
  """
  pos = description.find('\nChange-Id:')
  if pos == -1:
    raise StepFailure('No Change-Id found in %s %r' % (change, description))
  pos += 1  # We will insert text after the newline
  return description[:pos] + text + description[pos:]


def RunSteps(api: RecipeApi, properties: BuildToolchainProperties) -> None:
  with api.step.nest('check properties'):
    errors = []
    gs_re = re.compile(r'^gs:', re.IGNORECASE)
    if not properties.archive_gs_bucket:
      errors.append('archive_gs_bucket must be set')
    elif gs_re.match(properties.archive_gs_bucket):
      errors.append('archive_gs_bucket must not include "gs:" prefix')
    if not properties.prebuilts_gs_bucket:
      errors.append('prebuilts_gs_bucket must be set')
    elif gs_re.match(properties.prebuilts_gs_bucket):
      errors.append('prebuilts_gs_bucket must not include "gs:" prefix')
    if not properties.sdk_gs_bucket:
      errors.append('sdk_gs_bucket must be set')
    elif gs_re.match(properties.sdk_gs_bucket):
      errors.append('sdk_gs_bucket must not include "gs:" prefix')
    if errors:
      raise StepFailure('\n'.join(errors))

  # Unlike normal CrOS builds, the SDK has no concept of pinned CrOS manifest
  # or specific Chrome version.  Use a datestamp instead.
  version = api.time.utcnow().strftime('%Y.%m.%d.%H%M%S')
  version_year, version_month, _ = version.split('.', maxsplit=2)
  api.step.empty('new SDK version', step_text=version)

  with api.step.nest('identify key CLs'):
    # A toolchain update consists of a number of CLs that must be
    # landed together:
    #
    #  - The CL that makes the changes that necessitate a toolchain
    #    rebuild (e.g. a new LLVM, Rust, or library version).
    #
    #  - Binhost update CLs that point ChromiumOS at the newly-built
    #    toolchain.
    #
    #  - Optionally, additional CLs may be included.
    #
    # This step detects the binhost CLs (if present; they may not have
    # been generated yet) and chooses one non-binhost CL as the
    # "central" CL. The central CL will be made to cq-depend on the
    # binhost CLs once they have been generated.
    #
    # The mechanism for selecting the central CL is intentionally simple.
    #
    #  - Among the CLs that are part of this build, exactly one should
    #    be marked with Cq-Include-Trybots: {BUILDER}.
    #    That CL is the central CL.
    #
    # As a convenience, if no change has been marked with
    # Cq-Include-Trybots: {BUILDER}, but there is only one non-binhost
    # CL in the build, that CL is marked with Cq-Include-Trybots and
    # chosen as the central CL.
    #
    # TODO(b/251744856): Evaluate how well this works in practice and
    # see if a better strategy is called for.
    #
    central_cl = None
    central_cl_autodetected = False
    binhost_cls = {}
    trybot_re = re.compile(
        r'^Cq-Include-Trybots: %s\b' %
        (re.escape(api.buildbucket.builder_full_name),), re.MULTILINE)
    patch_sets = api.gerrit.fetch_patch_sets(api.build_menu.gerrit_changes,
                                             include_commit_info=True)

    non_binhost_cls = []
    conflicting_cls = set()
    binhost_cl_re = re.compile(
        r'updating .*\b(?:FULL_BINHOST|SDK_LATEST_VERSION|TC_PATH)\b')
    for change in patch_sets:
      if binhost_cl_re.search(change.subject):
        binhost_cls[change.display_id] = change
      else:
        non_binhost_cls.append(change)
        if trybot_re.search(change.commit_info['message']):
          if central_cl is not None:
            conflicting_cls.add(central_cl.display_id)
            conflicting_cls.add(change.display_id)
          else:
            central_cl = change

    if conflicting_cls:
      raise StepFailure(
          ('multiple CLs have Cq-Include-Trybots: %s set'
           ': %s') %
          (api.buildbucket.builder_full_name, ', '.join(conflicting_cls)))

    if central_cl is None:
      # If there is only one non-binhost CL, make it the central CL.
      if len(non_binhost_cls) == 1:
        central_cl = non_binhost_cls[0]
        central_cl_autodetected = True

    # After all this, there should be a central CL.
    if central_cl is None:
      raise StepFailure(
          ('Could not determine central CL.'
           ' Please set Cq-Include-Trybots: %s on exactly one CL.') %
          (api.buildbucket.builder_full_name,))

  with api.build_menu.configure_builder(
  ), api.build_menu.setup_workspace_and_chroot():
    # Check out the central CL on a branch. This is necessary for calling
    # api.gerrit.set_change_description(), which we will do later.
    with api.step.nest('ensure key CL branch is tracking upstream'):
      project_info = api.repo.project_info(central_cl.project)
      api.step('create named branch', [
          'git',
          '-C',
          project_info.path,
          'checkout',
          '-b',
          f'sdk{version}',
      ])
      api.step('set tracking branch', [
          'git',
          '-C',
          project_info.path,
          'branch',
          '--set-upstream-to',
          f'{project_info.remote}/{project_info.branch_name}',
      ])

    # If the central CL was autodetected, tag it so that we can reliably
    # track which one it was. This code is after setup_workspace_and_chroot()
    # to avoid b/283926323 "cwd is not a directory".
    if central_cl_autodetected:
      with api.step.nest('tag key CL'):
        description = central_cl.commit_info['message']
        trybots_str = 'Cq-Include-Trybots: %s\n' % (
            api.buildbucket.builder_full_name,)
        description = _insert_before_change_id(central_cl.display_id,
                                               description, trybots_str)
        api.gerrit.set_change_description(central_cl.to_gerrit_change_proto(),
                                          description)

    with api.step.nest('build SDK packages'):
      api.cros_build_api.SdkService.BuildPrebuilts(
          BuildPrebuiltsRequest(chroot=api.cros_sdk.chroot))

    with api.step.nest('create redistributable toolchains'):
      response = api.cros_build_api.SdkService.BuildSdkToolchain(
          BuildSdkToolchainRequest(
              chroot=api.cros_sdk.chroot,
              result_path=api.cros_build_api.new_result_path()))
      redistributable_toolchains = response.generated_files

    with api.step.nest('package SDK as tarball'):
      timestamp = api.buildbucket.build.start_time.ToDatetime().strftime(
          '%Y.%m.%d.%H%M%S')

      request = BuildSdkTarballRequest(
          chroot=api.cros_sdk.chroot,
          sdk_version=f'build-toolchain-{timestamp}',
      )

      tarball_path = api.cros_build_api.SdkService.BuildSdkTarball(
          request).sdk_tarball_path

    with api.step.nest('create manifest from SDK'):
      api.cros_build_api.SdkService.CreateManifestFromSdk(
          CreateManifestFromSdkRequest(
              chroot=api.cros_sdk.chroot,
              sdk_path=common_pb2.Path(
                  path=f'/build/{SDK_BUILD_TARGET}',
                  location=common_pb2.Path.INSIDE,
              ),
              dest_dir=common_pb2.Path(
                  path=str(api.workspace_util.workspace_path),
                  location=common_pb2.Path.OUTSIDE,
              ),
          ))

    with api.step.nest('upload SDK tarball'):
      # Compute upload location.
      # This is something like
      #     chromiumos-sdk/R110-15267.0.0-b5252087/built-sdk.tar.xz
      #
      # Which is composed of:
      #  - The builder name.
      #  - The ChromeOS version string.
      #  - The basename of the packaged SDK.
      upload_path = '/'.join([
          api.buildbucket.builder_name,
          str(api.cros_version.version),
          api.path.basename(tarball_path.path),
      ])
      # Upload the file to google storage (-n so we don't overwrite an
      # already existing file).
      api.gsutil.upload(tarball_path.path, properties.archive_gs_bucket,
                        upload_path, args=['-a', 'public-read', '-n'])

    with api.step.nest('upload redistributable toolchains'):
      for tc in redistributable_toolchains:
        # Compute upload location.
        # This is composed of:
        #  - The year of the SDK version.
        #  - The month of the SDK version.
        #  - The basename of the toolchain tarball, without extensions.
        #  - The SDK version.
        #  - The extensions.
        basename, extensions = os.path.basename(tc.path).split('.', maxsplit=1)
        upload_path = (f'{version_year}/'
                       f'{version_month}/'
                       f'{basename}-{version}'
                       f'.{extensions}')
        # Upload with -n to prevent overwriting already existing files.
        api.gsutil.upload(tc.path, properties.sdk_gs_bucket, upload_path,
                          args=['-a', 'public-read', '-n'])

    with api.step.nest('upload prebuilt packages'):
      api.cros_build_api.SdkService.UploadPrebuiltPackages(
          UploadPrebuiltPackagesRequest(
              chroot=api.cros_sdk.chroot,
              prepend_version=VERSION_PREFIX,
              version=version,
              upload_location=f'gs://{properties.prebuilts_gs_bucket}',
          ))

    with api.step.nest('create binhost CLs'):
      # Compute sdk_tarball_template. Note that the "%(target)s" part is
      # not filled in here. It will be written to the configuration file
      # to be filled in by users of the configuration file.
      year, month = version.split('.')[0:2]
      sdk_tarball_template = f'{year}/{month}/%(target)s-{version}{SDK_TARBALL_SUFFIX}'
      response = api.cros_build_api.SdkService.CreateBinhostCLs(
          CreateBinhostCLsRequest(
              prepend_version=VERSION_PREFIX,
              version=version,
              upload_location=properties.prebuilts_gs_bucket,
              sdk_tarball_template=sdk_tarball_template,
          ))
      new_binhost_cls = response.cls

    with api.step.nest('cq-depend on binhost CLs'):
      # If the central CL cq-depends on binhost CLs already, remove
      # those dependencies.
      gerrit_change = central_cl.to_gerrit_change_proto()
      description = api.gerrit.get_change_description(gerrit_change)
      binhost_re = '|'.join(re.escape(text) for text in binhost_cls)
      description = re.sub(
          r'^Cq-Depend: (?:%s)$' % (binhost_re,),
          '',
          description,
          flags=re.MULTILINE,
      )

      # Add cq-depends on the new binhost CLs.
      depends_str = ''.join(f'Cq-Depend: {cl}\n' for cl in new_binhost_cls)
      description = _insert_before_change_id(central_cl.display_id, description,
                                             depends_str)
      api.gerrit.set_change_description(gerrit_change, description)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  single_change_with_trybots = GerritChange(
      change=101,
      project='cromiumos/overlays/chromiumos-overlay',
      host='chromium-review.googlesource.com',
      patchset=1,
  )

  single_change_without_trybots = GerritChange(
      change=102,
      project='cromiumos/overlays/chromiumos-overlay',
      host='chromium-review.googlesource.com',
      patchset=1,
  )

  another_change_without_trybots = GerritChange(
      change=103,
      project='cromiumos/overlays/chromiumos-overlay',
      host='chromium-review.googlesource.com',
      patchset=1,
  )

  prebuilt_binhost_change = GerritChange(
      change=104,
      project='cromiumos/overlays/board-overlays',
      host='chromium-review.googlesource.com',
      patchset=1,
  )

  missing_change_id = GerritChange(
      change=105,
      project='cromiumos/overlays/chromiumos-overlay',
      host='chromium-review.googlesource.com',
      patchset=1,
  )

  another_change_with_trybots = GerritChange(
      change=106,
      project='cromiumos/overlays/chromiumos-overlay',
      host='chromium-review.googlesource.com',
      patchset=1,
  )

  sdk_version_change = GerritChange(
      change=107,
      project='cromiumos/overlays/chromiumos-overlay',
      host='chromium-review.googlesource.com',
      patchset=1,
  )

  fetch_changes_responses = {
      101: {
          'change_id': '101',
          'revision_info': {
              'commit': {
                  'message':
                      ('toolchain update test change\n'
                       '\nCq-Include-Trybots: chromeos/cq/chromeos-sdk-cq\n'
                       'Change-Id: Xabc\n'),
              },
          },
      },
      102: {
          'change_id': '102',
          'revision_info': {
              'commit': {
                  'message': ('simple toolchain update test change\n'
                              '\nChange-Id: Xdfg\n'),
              },
          },
      },
      103: {
          'change_id': '103',
          'revision_info': {
              'commit': {
                  'message': ('another change without trybots\n'
                              '\nChange-Id: Xghj\n'),
              },
          },
      },
      104: {
          'change_id': '104',
          'subject': 'prebuilt.conf: updating FULL_BINHOST',
          'revision_info': {
              'commit': {
                  'message': ('prebuilt.conf: updating FULL_BINHOST\n'
                              '\nChange-Id: Xjxl\n'),
              },
          },
      },
      105: {
          'change_id': '105',
          'subject': 'no change id',
          'revision_info': {
              'commit': {
                  'message': 'change without change-id\n',
              },
          },
      },
      106: {
          'change_id': '106',
          'subject': 'another change with trybots',
          'revision_info': {
              'commit': {
                  'message':
                      ('this change also has the trybots footer\n'
                       '\nCq-Include-Trybots: chromeos/cq/chromeos-sdk-cq\n'
                       '\nChange-Id: Xgli\n'),
              },
          },
      },
      107: {
          'change_id': '107',
          'subject': 'sdk_version.conf: updating SDK_LATEST_VERSION, TC_PATH',
          'revision_info': {
              'commit': {
                  'message': (
                      'sdk_version.conf: updating SDK_LATEST_VERSION, TC_PATH\n'
                      '\nChange-Id: Xttw\n'),
              },
          },
      },
  }

  def builder_args(**kwargs: Any) -> Dict[str, Any]:
    """Generate a test build."""
    kwargs.setdefault('cq', True)
    kwargs.setdefault('builder', 'chromeos-sdk-cq')
    return kwargs

  good_properties = BuildToolchainProperties(
      archive_gs_bucket='test-archive-bucket',
      prebuilts_gs_bucket='test-prebuilt-bucket',
      sdk_gs_bucket='test-sdk-bucket',
  )

  yield api.build_menu.test(
      'missing-archive-bucket',
      api.properties(
          BuildToolchainProperties(
              prebuilts_gs_bucket='prebuilt-bucket-is-here',
              sdk_gs_bucket='sdk-bucket-is-here')),
      api.post_check(post_process.MustRun, 'check properties'),
      api.post_check(post_process.DoesNotRun, 'identify key CLs'),
      api.post_check(post_process.SummaryMarkdown,
                     'archive_gs_bucket must be set'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'missing-prebuilts-bucket',
      api.properties(
          BuildToolchainProperties(archive_gs_bucket='archive-bucket-is-here',
                                   sdk_gs_bucket='sdk-bucket-is-here')),
      api.post_check(post_process.MustRun, 'check properties'),
      api.post_check(post_process.DoesNotRun, 'identify key CLs'),
      api.post_check(post_process.SummaryMarkdown,
                     'prebuilts_gs_bucket must be set'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'missing-sdk-bucket',
      api.properties(
          BuildToolchainProperties(
              archive_gs_bucket='archive-bucket-is-here',
              prebuilts_gs_bucket='prebuilt-bucket-is-here')),
      api.post_check(post_process.MustRun, 'check properties'),
      api.post_check(post_process.DoesNotRun, 'identify key CLs'),
      api.post_check(post_process.SummaryMarkdown, 'sdk_gs_bucket must be set'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'missing-multiple-buckets',
      api.post_check(post_process.MustRun, 'check properties'),
      api.post_check(post_process.DoesNotRun, 'identify key CLs'),
      api.post_check(
          post_process.SummaryMarkdown,
          'archive_gs_bucket must be set\nprebuilts_gs_bucket must be set\nsdk_gs_bucket must be set'
      ),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'buckets_include_gs',
      api.properties(
          BuildToolchainProperties(
              archive_gs_bucket='gs://archive-bucket-is-here',
              prebuilts_gs_bucket='gs://prebuilts-bucket-is-here',
              sdk_gs_bucket='gs://sdk-bucket-is-here')),
      api.post_check(post_process.MustRun, 'check properties'),
      api.post_check(post_process.DoesNotRun, 'identify key CLs'),
      api.post_check(post_process.SummaryMarkdown,
                     ('archive_gs_bucket must not include "gs:" prefix\n' +
                      'prebuilts_gs_bucket must not include "gs:" prefix\n' +
                      'sdk_gs_bucket must not include "gs:" prefix')),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'no-cl',
      api.properties(good_properties),
      api.gerrit.set_gerrit_fetch_changes_response('identify key CLs', [],
                                                   fetch_changes_responses),
      api.post_check(post_process.MustRun, 'check properties'),
      api.post_check(post_process.MustRun, 'identify key CLs'),
      api.post_check(post_process.DoesNotRun, 'build SDK packages'),
      api.post_check(post_process.DoesNotRun,
                     'upload redistributable toolchains'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilt packages'),
      api.post_check(post_process.DoesNotRun, 'create binhost CLs'),
      api.post_check(post_process.DoesNotRun, 'cq-depend on binhost CLs'),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[]),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'no-central-cl',
      api.properties(good_properties),
      api.gerrit.set_gerrit_fetch_changes_response(
          'identify key CLs',
          [single_change_without_trybots, another_change_without_trybots],
          fetch_changes_responses,
      ),
      api.post_check(post_process.MustRun, 'check properties'),
      api.post_check(post_process.MustRun, 'identify key CLs'),
      api.post_check(post_process.DoesNotRun, 'build SDK packages'),
      api.post_check(post_process.DoesNotRun,
                     'create redistributable toolchains'),
      api.post_check(post_process.DoesNotRun,
                     'upload redistributable toolchains'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilt packages'),
      api.post_check(post_process.DoesNotRun, 'create binhost CLs'),
      api.post_check(post_process.DoesNotRun, 'cq-depend on binhost CLs'),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[
          single_change_without_trybots,
          another_change_without_trybots,
      ]),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'no-change-id',
      api.properties(good_properties),
      api.gerrit.set_gerrit_fetch_changes_response('identify key CLs',
                                                   [missing_change_id],
                                                   fetch_changes_responses),
      api.post_check(post_process.MustRun, 'check properties'),
      api.post_check(post_process.MustRun, 'identify key CLs'),
      api.post_check(post_process.DoesNotRun, 'build SDK packages'),
      api.post_check(post_process.DoesNotRun,
                     'create redistributable toolchains'),
      api.post_check(post_process.DoesNotRun,
                     'upload redistributable toolchains'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilt packages'),
      api.post_check(post_process.DoesNotRun, 'create binhost CLs'),
      api.post_check(post_process.DoesNotRun, 'cq-depend on binhost CLs'),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[missing_change_id]),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'multiple-trybots-cls',
      api.properties(good_properties),
      api.gerrit.set_gerrit_fetch_changes_response(
          'identify key CLs',
          [single_change_with_trybots, another_change_with_trybots],
          fetch_changes_responses),
      api.post_check(post_process.MustRun, 'check properties'),
      api.post_check(post_process.MustRun, 'identify key CLs'),
      api.post_check(post_process.DoesNotRun, 'build SDK packages'),
      api.post_check(post_process.DoesNotRun,
                     'create redistributable toolchains'),
      api.post_check(post_process.DoesNotRun,
                     'upload redistributable toolchains'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilt packages'),
      api.post_check(post_process.DoesNotRun, 'create binhost CLs'),
      api.post_check(post_process.DoesNotRun, 'cq-depend on binhost CLs'),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[
          single_change_with_trybots, another_change_with_trybots
      ]),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'successful-run', api.properties(good_properties),
      api.gerrit.set_gerrit_fetch_changes_response(
          'identify key CLs',
          [single_change_with_trybots],
          fetch_changes_responses,
      ), api.post_check(post_process.MustRun, 'check properties'),
      api.post_check(post_process.MustRun, 'identify key CLs'),
      api.post_check(post_process.MustRun, 'build SDK packages'),
      api.post_check(post_process.MustRun, 'create redistributable toolchains'),
      api.post_check(post_process.MustRun, 'package SDK as tarball'),
      api.post_check(post_process.MustRun, 'create manifest from SDK'),
      api.post_check(post_process.MustRun, 'upload SDK tarball'),
      api.post_check(post_process.MustRun, 'upload redistributable toolchains'),
      api.post_check(post_process.MustRun, 'upload prebuilt packages'),
      api.post_check(post_process.MustRun, 'create binhost CLs'),
      api.post_check(post_process.MustRun, 'cq-depend on binhost CLs'),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[single_change_with_trybots]))

  yield api.build_menu.test(
      'successful-run-no-include-trybots', api.properties(good_properties),
      api.gerrit.set_gerrit_fetch_changes_response(
          'identify key CLs',
          [single_change_without_trybots],
          fetch_changes_responses,
      ), api.post_check(post_process.MustRun, 'check properties'),
      api.post_check(post_process.MustRun, 'identify key CLs'),
      api.post_check(post_process.MustRun, 'tag key CL'),
      api.post_check(post_process.MustRun, 'build SDK packages'),
      api.post_check(post_process.MustRun, 'create redistributable toolchains'),
      api.post_check(post_process.MustRun, 'package SDK as tarball'),
      api.post_check(post_process.MustRun, 'create manifest from SDK'),
      api.post_check(post_process.MustRun, 'upload SDK tarball'),
      api.post_check(post_process.MustRun, 'upload redistributable toolchains'),
      api.post_check(post_process.MustRun, 'upload prebuilt packages'),
      api.post_check(post_process.MustRun, 'create binhost CLs'),
      api.post_check(post_process.MustRun, 'cq-depend on binhost CLs'),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[single_change_without_trybots]))

  yield api.build_menu.test(
      'successful-run-with-binhost-cl', api.properties(good_properties),
      api.gerrit.set_gerrit_fetch_changes_response(
          'identify key CLs',
          [
              single_change_without_trybots, prebuilt_binhost_change,
              sdk_version_change
          ],
          fetch_changes_responses,
      ), api.post_check(post_process.MustRun, 'check properties'),
      api.post_check(post_process.MustRun, 'identify key CLs'),
      api.post_check(post_process.MustRun, 'build SDK packages'),
      api.post_check(post_process.MustRun, 'create redistributable toolchains'),
      api.post_check(post_process.MustRun, 'package SDK as tarball'),
      api.post_check(post_process.MustRun, 'create manifest from SDK'),
      api.post_check(post_process.MustRun, 'upload SDK tarball'),
      api.post_check(post_process.MustRun, 'upload redistributable toolchains'),
      api.post_check(post_process.MustRun, 'upload prebuilt packages'),
      api.post_check(post_process.MustRun, 'create binhost CLs'),
      api.post_check(post_process.MustRun, 'cq-depend on binhost CLs'),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[
          single_change_without_trybots,
          prebuilt_binhost_change,
          sdk_version_change,
      ]))

  yield api.build_menu.test(
      'build_sdk_packages-failed',
      api.properties(good_properties),
      api.gerrit.set_gerrit_fetch_changes_response(
          'identify key CLs',
          [single_change_with_trybots],
          fetch_changes_responses,
      ),
      api.post_check(post_process.MustRun, 'check properties'),
      api.post_check(post_process.MustRun, 'identify key CLs'),
      api.post_check(post_process.MustRun, 'build SDK packages'),
      api.post_check(post_process.DoesNotRun, 'package SDK as tarball'),
      api.post_check(post_process.DoesNotRun, 'create manifest from SDK'),
      api.post_check(post_process.DoesNotRun, 'upload SDK tarball'),
      api.post_check(post_process.DoesNotRun,
                     'upload redistributable toolchains'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilt packages'),
      api.post_check(post_process.DoesNotRun, 'create binhost CLs'),
      api.post_check(post_process.DoesNotRun, 'cq-depend on binhost CLs'),
      api.build_menu.set_build_api_return('build SDK packages',
                                          'SdkService/BuildPrebuilts',
                                          retcode=1),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[single_change_with_trybots]),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'create_redistributable_toolchains-failed',
      api.properties(good_properties),
      api.gerrit.set_gerrit_fetch_changes_response(
          'identify key CLs',
          [single_change_with_trybots],
          fetch_changes_responses,
      ),
      api.post_check(post_process.MustRun, 'check properties'),
      api.post_check(post_process.MustRun, 'identify key CLs'),
      api.post_check(post_process.MustRun, 'create redistributable toolchains'),
      api.post_check(post_process.DoesNotRun, 'upload SDK tarball'),
      api.post_check(post_process.DoesNotRun,
                     'upload redistributable toolchains'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilt packages'),
      api.post_check(post_process.DoesNotRun, 'create binhost CLs'),
      api.post_check(post_process.DoesNotRun, 'cq-depend on binhost CLs'),
      api.build_menu.set_build_api_return('create redistributable toolchains',
                                          'SdkService/BuildSdkToolchain',
                                          retcode=1),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[single_change_with_trybots]),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'package_sdk-failed',
      api.properties(good_properties),
      api.gerrit.set_gerrit_fetch_changes_response(
          'identify key CLs',
          [single_change_with_trybots],
          fetch_changes_responses,
      ),
      api.post_check(post_process.MustRun, 'check properties'),
      api.post_check(post_process.MustRun, 'identify key CLs'),
      api.post_check(post_process.MustRun, 'build SDK packages'),
      api.post_check(post_process.MustRun, 'package SDK as tarball'),
      api.post_check(post_process.DoesNotRun, 'create manifest from SDK'),
      api.post_check(post_process.DoesNotRun, 'upload SDK tarball'),
      api.post_check(post_process.DoesNotRun,
                     'upload redistributable toolchains'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilt packages'),
      api.post_check(post_process.DoesNotRun, 'create binhost CLs'),
      api.post_check(post_process.DoesNotRun, 'cq-depend on binhost CLs'),
      api.build_menu.set_build_api_return('package SDK as tarball',
                                          'SdkService/BuildSdkTarball',
                                          retcode=1),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[single_change_with_trybots]),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'create_manifest-failed',
      api.properties(good_properties),
      api.gerrit.set_gerrit_fetch_changes_response(
          'identify key CLs',
          [single_change_with_trybots],
          fetch_changes_responses,
      ),
      api.post_check(post_process.DoesNotRun, 'upload SDK tarball'),
      api.post_check(post_process.DoesNotRun,
                     'upload redistributable toolchains'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilt packages'),
      api.post_check(post_process.DoesNotRun, 'create binhost CLs'),
      api.post_check(post_process.DoesNotRun, 'cq-depend on binhost CLs'),
      api.build_menu.set_build_api_return('create manifest from SDK',
                                          'SdkService/CreateManifestFromSdk',
                                          retcode=1),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[single_change_with_trybots]),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'upload_sdk_tarball-failed',
      api.properties(good_properties),
      api.gerrit.set_gerrit_fetch_changes_response(
          'identify key CLs',
          [single_change_with_trybots],
          fetch_changes_responses,
      ),
      api.post_check(post_process.MustRun, 'check properties'),
      api.post_check(post_process.MustRun, 'identify key CLs'),
      api.post_check(post_process.MustRun, 'build SDK packages'),
      api.post_check(post_process.MustRun, 'package SDK as tarball'),
      api.post_check(post_process.MustRun, 'create manifest from SDK'),
      api.post_check(post_process.MustRun, 'upload SDK tarball'),
      api.post_check(post_process.DoesNotRun,
                     'upload redistributable toolchains'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilt packages'),
      api.post_check(post_process.DoesNotRun, 'create binhost CLs'),
      api.post_check(post_process.DoesNotRun, 'cq-depend on binhost CLs'),
      api.step_data('upload SDK tarball.gsutil upload', retcode=1),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[single_change_with_trybots]),
      status='INFRA_FAILURE',
  )

  yield api.build_menu.test(
      'upload_redistributable_toolchains-failed',
      api.properties(good_properties),
      api.gerrit.set_gerrit_fetch_changes_response(
          'identify key CLs',
          [single_change_with_trybots],
          fetch_changes_responses,
      ),
      api.post_check(post_process.DoesNotRun, 'create binhost CLs'),
      api.post_check(post_process.DoesNotRun, 'cq-depend on binhost CLs'),
      api.step_data(
          'upload redistributable toolchains.gsutil upload',
          retcode=1,
      ),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[single_change_with_trybots]),
      status='INFRA_FAILURE',
  )

  yield api.build_menu.test(
      'upload_prebuilt_packages-failed',
      api.properties(good_properties),
      api.gerrit.set_gerrit_fetch_changes_response(
          'identify key CLs',
          [single_change_with_trybots],
          fetch_changes_responses,
      ),
      api.post_check(post_process.DoesNotRun, 'create binhost CLs'),
      api.post_check(post_process.DoesNotRun, 'cq-depend on binhost CLs'),
      api.build_menu.set_build_api_return(
          'upload prebuilt packages',
          'SdkService/UploadPrebuiltPackages',
          retcode=1,
      ),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[single_change_with_trybots]),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'create-binhost-cls-failed',
      api.properties(good_properties),
      api.gerrit.set_gerrit_fetch_changes_response(
          'identify key CLs',
          [single_change_with_trybots],
          fetch_changes_responses,
      ),
      api.post_check(post_process.DoesNotRun, 'cq-depend on binhost CLs'),
      api.build_menu.set_build_api_return('create binhost CLs',
                                          'SdkService/CreateBinhostCLs',
                                          retcode=1),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[single_change_with_trybots]),
      status='FAILURE',
  )
