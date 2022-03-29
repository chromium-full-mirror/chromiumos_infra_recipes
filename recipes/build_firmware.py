# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that builds and tests firmware.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
"""

DEPS = [
    'depot_tools/gitiles',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/properties',
    'recipe_engine/step',
    'build_menu',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'easy',
    'src_state',
    'test_util',
]

import xml.etree.ElementTree as ET

from google.protobuf.json_format import MessageToDict
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

from PB.chromite.api.firmware import (BuildAllFirmwareRequest,
                                      TestAllFirmwareRequest)
from PB.recipes.chromeos.build_firmware import BuildFirmwareProperties

PROPERTIES = BuildFirmwareProperties

TEST_MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <include name="_remotes.xml" />
  <default revision="refs/heads/main"
           remote="cros"
           sync-j="8" />
  <project path="src/platform/ti50/common"
           remote="cros-internal"
           name="ti50/common/ti50"
           revision="123"
           groups="firmware" />
</manifest>
"""


def RunSteps(api, properties):
  with api.build_menu.configure_builder() \
     as config, api.build_menu.setup_workspace():
    chromiumos_sdk_version = _read_chromiumos_sdk_pin(api, properties)
    api.build_menu.setup_chroot(sdk_version=chromiumos_sdk_version)

    service = api.cros_build_api.FirmwareService
    chroot = api.cros_sdk.chroot
    location = properties.firmware_location or config.general.firmware_location
    response = service.BuildAllFirmware(
        BuildAllFirmwareRequest(firmware_location=location, chroot=chroot,
                                code_coverage=properties.code_coverage),
        name='build firmware')
    binary_sizes = {}
    if response.metrics and response.metrics.value:
      for fw_metric in response.metrics.value:
        for fw_section in fw_metric.fw_section:
          if fw_section.track_on_gerrit:
            binary_sizes[fw_section.region] = fw_section.used

    if binary_sizes:
      api.easy.set_properties_step(binary_sizes=binary_sizes,
                                   step_name='output binary sizes')
    if properties.set_got_revision:
      with api.step.nest('set got_revision'):
        api.easy.set_properties_step(
            got_revision=_get_ti50_commit(api), step_name='output got_revision')

    service.TestAllFirmware(
        TestAllFirmwareRequest(firmware_location=location, chroot=chroot,
                               code_coverage=properties.code_coverage),
        name='test firmware')

    uploaded_artifacts = None
    if properties.working_artifacts:
      uploaded_artifacts = api.build_menu.upload_artifacts(config=config)
    else:
      # TODO(b/177907749): Once we have artifacts in all of the builders, stop
      # ignoring failures.
      with api.step.nest('try to upload artifacts') as pres:
        try:
          uploaded_artifacts = api.build_menu.upload_artifacts(config=config)
        except StepFailure as ex:
          pres.step_text = ex.reason_message()

    # Invoke signing if applies.
    build = api.buildbucket.build
    if _invoke_signing_for_current_build(build.builder.builder,
                                         uploaded_artifacts, properties):
      with api.step.nest('schedule signing build') as pres:
        requests = []
        sign_image_props = MessageToDict(properties.sign_image_properties,
                                         preserving_proto_field_name=True)
        bucket = 'staging' if api.build_menu.is_staging else 'release'
        builder = 'staging-sign-image' if api.build_menu.is_staging else 'sign-image'
        for artifact_name in uploaded_artifacts[2]['FIRMWARE_TARBALL']:
          archive = "gs://%s/%s/%s" % (uploaded_artifacts[0],
                                       uploaded_artifacts[1], artifact_name)
          sign_image_props["archive"] = archive
          requests.append(
              api.buildbucket.schedule_request(bucket=bucket, builder=builder,
                                               properties=sign_image_props))

        api.buildbucket.schedule(requests)


def _read_chromiumos_sdk_pin(api, properties):
  if properties.chromiumos_sdk_pin_file:
    with api.step.nest('read chromiumos-sdk pin'):
      filepath = api.src_state.workspace_path.join(
          properties.chromiumos_sdk_pin_file)
      return api.file.read_text('read {}'.format(filepath), filepath).strip()
  return None


def _get_ti50_commit(api):
  '''
  Get the ti50 commit that we're at in the current snapshot.

  We need to use the commit for this repository for the binary-size plugin.
  See b/200577083 for context.
  '''
  manifest_contents = api.cros_source.pinned_manifest
  root = ET.fromstring(manifest_contents)
  return root.findall(
      './/project[@path="src/platform/ti50/common"]')[0].attrib['revision']


def _invoke_signing_for_current_build(builder_name, uploaded_artifacts,
                                      properties):
  '''
  Whether signing for current build should be invoked.

  Args:
    builder_name (str): Current builder name.
    uploaded_artifacts (UploadedArtifacts): Uploaded artifacts.
    properties (BuildFirmwareProperties): Build firmware properties for current build.

  Returns:
    (bool): True if signing should be invoked. False otherwise.
  '''
  valid_builder = builder_name in properties.signing_allowed_builder_names and properties.sign_image_properties
  artifact_upload_succeeded = uploaded_artifacts and len(uploaded_artifacts) > 2
  return valid_builder and artifact_upload_succeeded


def GenTests(api):

  def get_signing_image_props_for_test(is_staging=False):
    '''
    Get SignImageProperties for test.

    Args:
      is_staging (bool): Whether properties need for staging.

    Returns:
      (dict): SignImageProperties object as dict for testing.
    '''
    return {
        "image_type": 13,
        "channel": 0,
        "keyset": "test-keyset",
        "signer_type": 2 if is_staging else 1,
        "allow_non_release_signer_bucket": True,
        "gsc_instructions": {
            "target": 1,
        },
    }

  def test(name, *args, **kwargs):
    kwargs.setdefault('builder', 'fw-ec-postsubmit')
    kwargs.setdefault('input_properties', dict(firmware_location=1))
    build = api.test_util.test_child_build(None, **kwargs).build
    return api.test(name, build, *args)

  yield test(
      'postsubmit',
      api.override_step_data(
          'sync to gitiles commit.fetch snapshot-HEAD-SHA:snapshot.xml',
          api.gitiles.make_encoded_file(TEST_MANIFEST)))

  yield test(
      'cq',
      api.override_step_data(
          'sync to gitiles commit.fetch snapshot-HEAD-SHA:snapshot.xml',
          api.gitiles.make_encoded_file(TEST_MANIFEST)),
      cq=True,
      builder='fw-ec-cq',
  )

  sdk_pin_path = 'src/platform/ti50/sdk-version'
  yield test(
      'firmware-ti50-cq', api.properties(set_got_revision=True),
      api.override_step_data(
          'sync to gitiles commit.fetch snapshot-HEAD-SHA:snapshot.xml',
          api.gitiles.make_encoded_file(TEST_MANIFEST)),
      api.step_data(
          'read chromiumos-sdk pin.read [CLEANUP]/chromiumos_workspace/{}'
          .format(sdk_pin_path), api.file.read_text('2022.01.20.073008\n')),
      cq=True, builder='firmware-ti50-cq', input_properties=dict(
          firmware_location=3,
          chromiumos_sdk_pin_file=sdk_pin_path,
      ))

  yield test(
      'upload_fail',
      api.override_step_data(
          'sync to gitiles commit.fetch snapshot-HEAD-SHA:snapshot.xml',
          api.gitiles.make_encoded_file(TEST_MANIFEST)),
      api.cros_build_api.set_api_return(
          'try to upload artifacts.upload artifacts',
          'FirmwareService/BundleFirmwareArtifacts', retcode=1),
      api.post_check(post_process.StatusSuccess))

  yield test(
      'working_upload_fail',
      api.override_step_data(
          'sync to gitiles commit.fetch snapshot-HEAD-SHA:snapshot.xml',
          api.gitiles.make_encoded_file(TEST_MANIFEST)),
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          retcode=1), api.post_check(post_process.StatusAnyFailure),
      api.post_check(post_process.DoesNotRun, 'schedule signing build'),
      input_properties=(dict(firmware_location=1, working_artifacts=True)))

  yield test(
      'signing_invocation',
      api.override_step_data(
          'sync to gitiles commit.fetch snapshot-HEAD-SHA:snapshot.xml',
          api.gitiles.make_encoded_file(TEST_MANIFEST)),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun, 'schedule signing build'),
      builder='fw-ec-postsubmit', input_properties=(dict(
          firmware_location=1,
          signing_allowed_builder_names=['fw-ec-postsubmit'],
          sign_image_properties=get_signing_image_props_for_test(),
      )))

  yield test(
      'staging_signing_invocation',
      api.override_step_data(
          'sync to gitiles commit.fetch staging-snapshot-HEAD-SHA:snapshot.xml',
          api.gitiles.make_encoded_file(TEST_MANIFEST)),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun, 'schedule signing build'),
      builder='fw-ec-postsubmit', bucket='staging', input_properties=(dict(
          firmware_location=1,
          signing_allowed_builder_names=['fw-ec-postsubmit'],
          sign_image_properties=get_signing_image_props_for_test(
              is_staging=True),
      )))

  yield test(
      'output_binary_sizes', api.properties(set_got_revision=True),
      api.override_step_data(
          'sync to gitiles commit.fetch snapshot-HEAD-SHA:snapshot.xml',
          api.gitiles.make_encoded_file(TEST_MANIFEST)),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun, 'output binary sizes'),
      api.post_check(post_process.MustRun,
                     'set got_revision.output got_revision'))
