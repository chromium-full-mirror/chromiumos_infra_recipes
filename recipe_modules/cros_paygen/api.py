# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with Paygen and its config."""

import json
from copy import deepcopy
from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure
from os import path

from PB.chromite.api.payload import DLCImage as DLCImage_pb2
from PB.chromite.api.payload import GenerationRequest
from PB.chromite.api.payload import SignedImage as SignedImage_pb2
from PB.chromite.api.payload import UnsignedImage as UnsignedImage_pb2

import PB.chromiumos.common as common_pb2

DEFAULT_DELTA_TYPES = [
    'STEPPING_STONE', 'OMAHA', 'NO_DELTA', 'MILESTONE', 'FSI'
]

PAYGEN_JSON_GS_PATH = 'gs://chromeos-build-release-console/paygen.json'


class PaygenTestConfig(object):
  """A single test configuration.

  Stores and generates arguments for running autoupdate_EndToEndTest.

  Paygen Autotest documentation:
  go/cros-au-testplan#heading=h.9pokikke2eh

  autoupdate_EndToEndTest control file:
  http://cs/chromeos_public/src/third_party/autotest/files/server/site_tests/autoupdate_EndToEndTest/control

  autoupdate_EndToEndTest file:
  https://source.corp.google.com/chromeos_public/src/third_party/autotest/files/server/site_tests/autoupdate_EndToEndTest/autoupdate_EndToEndTest.py

  Example cros_test_platform build which enumerates the tests:
  https://ci.chromium.org/b/8865978197367928464

  Example test_runner build which invokes the autoupdate_EndToEndTest with the
  appropriate test arguments:
  https://ci.chromium.org/b/8865978162264605344
  """

  _AUTOTEST_TEST_NAME = 'autoupdate_EndToEndTest'
  _PAYGEN_AU_SUITE_TEMPLATE = 'paygen_au_%s'

  _UNIQUE_NAME_SUFFIX_TEMPLATE = (
      '%(suite_name)s_%(update_type)s_%(src_version)s_%(delta_type)s')
  _DISPLAY_NAME_TEMPLATE = (
      '%(build_target_name)s-release/%(tgt_archive_basename)s/%(suite_name)s/'
      '%(test_name)s_%(unique_name_suffix)s')

  def __init__(self, build_target_name, tgt_channel, tgt_version,
               tgt_payload_uri, tgt_archive_uri, is_delta_update, delta_type,
               src_version, src_payload_uri, src_artifact_uri,
               applicable_models=None):
    """Initialize a test configuration.

    Args:
      build_target_name (str): The name of the build target being tested
        (e.g. auron_paine).
      tgt_channel (str): The channel of the target payload
        (e.g. 'canary-channel').
      tgt_version (str): The target image version (e.g. '13373.0.0').
      tgt_payload_uri (str): The target payload URI.
      tgt_archive_uri (str): The location of target build archive artifacts.
      is_delta_update (bool): Whether this is a delta update test.
      delta_type (DeltaType): The type of update to do with the payload.
      src_version (str): The source image version (e.g. '13373.0.0').
      src_payload_uri (str): The source payload URI.
      src_artifact_uri (str): The location of source build artifacts.
      applicable_models (list[str]): A list of models that this config should
        run against. None indicates it can run on any build_target.
    """
    self._build_target_name = build_target_name
    self._tgt_channel = tgt_channel
    self._tgt_version = tgt_version
    self._tgt_payload_uri = tgt_payload_uri
    self._tgt_archive_uri = tgt_archive_uri

    self._src_version = src_version
    self._src_payload_uri = src_payload_uri
    self._src_artifact_uri = src_artifact_uri

    self._tgt_archive_basename = path.basename(self._tgt_archive_uri)
    self._update_type = 'delta' if is_delta_update else 'full'
    self._delta_type = delta_type
    self._applicable_models = applicable_models

  @property
  def display_name(self):
    """The display name for the autotest invocation."""
    return self._DISPLAY_NAME_TEMPLATE % {
        'build_target_name': self._build_target_name,
        'tgt_archive_basename': self._tgt_archive_basename,
        'suite_name': self.suite_name,
        'test_name': self._AUTOTEST_TEST_NAME,
        'unique_name_suffix': self._get_unique_name_suffix(),
    }

  def _get_unique_name_suffix(self):
    """Create a unique name suffix for the test config."""
    return self._UNIQUE_NAME_SUFFIX_TEMPLATE % {
        'suite_name': self.suite_name,
        'update_type': self._update_type,
        'src_version': self._src_version,
        'delta_type': self._delta_type.lower()
    }

  @property
  def suite_name(self):
    """The name of the test suite."""
    short_channel = self._tgt_channel.split('-')[0]
    return self._PAYGEN_AU_SUITE_TEMPLATE % short_channel

  @property
  def test_args(self):  #pragma: nocover
    """Test arguments with which to invoke the autotest control file."""
    template = '%s=%s'
    arg_values = [('name', self.suite_name), ('update_type', self._update_type),
                  ('source_release', self._src_version),
                  ('target_release', self._tgt_version),
                  ('target_payload_uri', self._tgt_payload_uri),
                  ('SUITE', self.suite_name),
                  ('source_payload_uri', self._src_payload_uri),
                  ('source_archive_uri', self._src_artifact_uri),
                  ('payload_type', self._delta_type)]

    return ' '.join(template % (key, val) for key, val in arg_values)


class CrosPaygenApi(recipe_api.RecipeApi):
  """A module for CrOS-specific paygen steps."""

  def __init__(self, *args, **kwargs):
    super(CrosPaygenApi, self).__init__(*args, **kwargs)
    self._internal_config = None
    self._paygen_json_gs_path = PAYGEN_JSON_GS_PATH

  @property
  def _config(self):
    """Lazily loaded copy of the entire configuration in paygen.json."""
    if not self._internal_config:
      raw_config = self._get_gs_config()
      try:
        self._internal_config = json.loads(raw_config)
      except ValueError:
        raise StepFailure('config json could not be deserialized')
      # Sanity check the configuration.
      if ('delta' not in self._internal_config or
          len(self._internal_config['delta']) == 0):
        raise StepFailure('config json was not formatted correctly')
    # Returns immutable copy.
    return deepcopy(self._internal_config)

  def _get_gs_config(self):
    """Pull and load the current paygen configuration as a string."""
    with self.m.step.nest('get paygen json') as pres:
      cat_res = self.m.gsutil.cat(self._paygen_json_gs_path, infra_step=True,
                                  stdout=self.m.raw_io.output())
      ret = cat_res.stdout.strip()
      pres.logs['paygen.json'] = ret
      return ret

  def _flatten_config(self, board_config):
    """Flatten a board_config so we can query it more easily."""
    new_b = deepcopy(board_config)
    new_b.update(board_config['board'])
    del new_b['board']
    return new_b

  @property
  def default_delta_types(self):
    return DEFAULT_DELTA_TYPES

  def get_builder_config(self, builder_name, **kwargs):
    """Return the configs matching the query or [].

    Note that all comparisons are made _in lower case_!

    Args:
      builder_name (str): The name of the builders to return configuration for.
      **kwargs: Match keyword to top level dictionary contents. For example
                passing delta_payload_tests=true will match only if matched.

    Returns:
      A list of dictionaries of the matching configurations. For example:

      [
       {
        "board": {
                "public_codename": "cyan",
                "is_active": true,
                "builder_name": "cyan"
        },
        "delta_type": "MILESTONE",
        "channel": "stable",
        "chrome_os_version": "13020.87.0",
        "chrome_version": "83.0.4103.119",
        "milestone": 83,
        "generate_delta": true,
        "delta_payload_tests": true,
        "full_payload_tests": false
        },
       {...},
       {...}
      ]
    """
    match_boards = []
    for b in self._config['delta']:
      b = self._flatten_config(b)
      if b['builder_name'].lower() == builder_name.lower():
        if all(
            [k in b and b[k].lower() == v.lower() for k, v in kwargs.items()]):
          match_boards.append(b)
    return match_boards

  def get_n2n_requests(self, tgt_artifacts, bucket, verify, dryrun):
    """Generate a N2N testing payloads.

    We will examine all the artifacts in tgt artifacts for unsigned
    test images and generate n2n requests (a request that updates to
    and from the same version.

    Args:
      tgt_artifacts (list[cros_storage.Image]): Available tgt images.
      bucket (str): The bucket containing the requests (and destination).
      verify (bool): Should we run payload verification.
      dryrun (bool): Should we not upload resulting artifacts.

    Returns:
      A list[GenerationRequest] or [].
    """
    reqs = []
    for tgt in tgt_artifacts:
      if (tgt.image_type == common_pb2.ImageType.Value('TEST') and
          isinstance(tgt, UnsignedImage_pb2)):
        reqs.append(
            GenerationRequest(src_unsigned_image=tgt, tgt_unsigned_image=tgt,
                              bucket=bucket, verify=verify, keyset='',
                              dryrun=dryrun))
    return reqs

  def get_delta_requests(self, payload_def, src_artifacts, tgt_artifacts,
                         bucket, verify, keyset, dryrun):
    """Examine def, source, and target and return list(GenerationRequests).

    If there isn't a matching source and target available, then return [].

    bucket, verify, keyset, and dryrun are all used to fill out the
    GenerationRequest().

    Args:
      payload_def (dict): A singular configuration from pulled config.
      src_artifacts (list[cros_storage.Image]): Available src images.
      tgt_artifacts (list[cros_storage.Image]): Available tgt images.
      bucket (str): The bucket containing the requests (and destination).
      verify (bool): Should we run payload verification.
      keyset (str): The keyset of the payload.
      dryrun (bool): Should we not upload resulting artifacts.

    Returns:
      A completed list[GenerationRequest] or [].
    """
    reqs = []

    # See if we're configured to do deltas at all.
    if not payload_def['generate_delta']:
      return reqs  # pragma: nocover

    # For each src query all the target artifacts for a match (naively).
    for tgt in tgt_artifacts:
      tgt_type = type(tgt)
      for src in src_artifacts:
        # Create and compare the versions, we don't paygen backwards.
        v_src = self.m.cros_version.Version.from_string(src.build.version)
        v_tgt = self.m.cros_version.Version.from_string(tgt.build.version)

        if v_tgt <= v_src:
          # TODO(crbug.com/1122854): Add test, remove pragma.
          continue  # pragma: nocover

        # Validate the artifact pair.
        if (tgt_type != type(src) or tgt.image_type != src.image_type or
            tgt.build.channel != src.build.channel or
            src.build.version != payload_def['chrome_os_version']):
          continue  # pragma: nocover

        elif isinstance(src, SignedImage_pb2):
          reqs.append(
              GenerationRequest(src_signed_image=src, tgt_signed_image=tgt,
                                bucket=bucket, verify=verify, keyset=keyset,
                                dryrun=dryrun))
        elif isinstance(src, UnsignedImage_pb2):
          # We don't create delta paygens for unsigned recovery images.
          if src.image_type == common_pb2.ImageType.Value('RECOVERY'):
            continue  # pragma: nocover
          reqs.append(
              GenerationRequest(src_unsigned_image=src, tgt_unsigned_image=tgt,
                                bucket=bucket, verify=verify, keyset=keyset,
                                dryrun=dryrun))
        elif isinstance(src, DLCImage_pb2):
          if not self.m.cros_storage.DLCImage.compatible(tgt, src):
            continue  # pragma: nocover
          reqs.append(
              GenerationRequest(src_dlc_image=src, tgt_dlc_image=tgt,
                                bucket=bucket, verify=verify, keyset='',
                                dryrun=dryrun))
    return reqs

  def get_full_requests(self, tgt_artifacts, bucket, verify, keyset, dryrun):
    """Get the configured full requests for a set of artifacts.

    Args:
      tgt_artifacts (list[cros_storage.Image]): Available tgt images.
      bucket (str): The bucket containing the requests (and destination).
      verify (bool): Should we run payload verification.
      keyset (str): The keyset of the payload.
      dryrun (bool): Should we not upload resulting artifacts.

    Returns:
      A completed list[GenerationRequest] or [].
    """
    reqs = []
    for tgt in tgt_artifacts:
      if isinstance(tgt, SignedImage_pb2):
        reqs.append(
            GenerationRequest(full_update=True, tgt_signed_image=tgt,
                              bucket=bucket, verify=verify, keyset=keyset,
                              dryrun=dryrun))
      elif isinstance(tgt, UnsignedImage_pb2):
        # We don't create full payloads for unsigned recovery images.
        if tgt.image_type == common_pb2.ImageType.Value('RECOVERY'):
          continue  #  pragma: nocover
        reqs.append(
            GenerationRequest(full_update=True, tgt_unsigned_image=tgt,
                              bucket=bucket, verify=verify, keyset=keyset,
                              dryrun=dryrun))
      elif isinstance(tgt, DLCImage_pb2):
        reqs.append(
            GenerationRequest(full_update=True, tgt_dlc_image=tgt,
                              bucket=bucket, verify=verify, keyset='',
                              dryrun=dryrun))

    # TODO(crbug.com/1122854): The chromite code checks the number of mp and
    # premp signing requests here. We are generally more relaxed at enforcing
    # this at the moment. We maybe revist this philosophy generally as we
    # approach launching this.
    return reqs

  def create_paygen_test_config(self, tgt_payload, delta_type, src_version=None,
                                src_channel=None, applicable_models=None):
    """Create a PaygenTestConfig for a test FullPayload or DeltaPayload.

    Args:
      tgt_payload (Payload): The payload to be tested.
      delta_type (DeltaType): The type of update we are doing with this payload.
      src_version (str): The version of the image to test updating from
        (e.g. '13373.0.0'). Required if the payload is a FullPayload, required
        to be None if it's a DeltaPayload.
      src_channel (str): The channel of the image to test updating from
        (e.g. 'canary-channel'). Required if the payload is a FullPayload,
        required to be None if it's a DeltaPayload.
      applicable_models (list(str)): A list of models that a paygen test should
        run against.

    Returns:
      A PaygenTestConfig or None if no source payload exists or unsupported
      Payload provided.
    """
    # TODO(crbug.com/1122854): Figure out how to enforce argument correctness.
    # Currently invalid argument combinations silently return None.
    tgt_image = tgt_payload._tgt_image
    build_target_name = tgt_image._artifact_root.build_target_name
    tgt_channel = tgt_image._artifact_root.channel
    tgt_version = tgt_image._artifact_root.version

    if isinstance(tgt_payload, self.m.cros_storage.DeltaPayload):
      is_delta_update = True
      src_image = tgt_payload._src_image
      src_version = src_image._artifact_root.version
    elif isinstance(tgt_payload, self.m.cros_storage.FullPayload):
      if not (src_version and src_channel):
        raise StepFailure(
            'source version and channel must be specified for FullPayload AU tests'
        )
      is_delta_update = False
      src_artifact_root = self.m.cros_storage.ArtifactRoot(
          bucket=tgt_image._artifact_root.bucket,
          build_target_name=build_target_name, channel=src_channel,
          version=src_version)
      src_image = self.m.cros_storage.UnsignedImage(
          artifact_root=src_artifact_root, milestone=tgt_image._milestone,
          image_type=common_pb2.ImageType.Value('TEST'))
    else:
      # Invalid Payload type given.
      raise StepFailure(
          'AU tests only supported for FullPayloads or DeltaPayloads')

    # Get source full test payload
    src_payloads = self.m.cros_storage.discover_gs_artifacts(
        src_image._artifact_root.uri,
        parse_types=[self.m.cros_storage.FullPayload.parse_uri])
    src_payload = None
    for payload in src_payloads:
      if not payload.key:
        src_payload = payload
        break
    if not src_payload:
      raise StepFailure('no source payload found')
    tgt_archive_uri = tgt_image.archive_uri
    src_artifact_uri = src_image._artifact_root.uri

    return PaygenTestConfig(
        build_target_name=build_target_name, tgt_channel=tgt_channel,
        tgt_payload_uri=tgt_payload.uri, tgt_archive_uri=tgt_archive_uri,
        tgt_version=tgt_version, src_payload_uri=src_payload.uri,
        src_artifact_uri=src_artifact_uri, src_version=src_version,
        is_delta_update=is_delta_update, delta_type=delta_type,
        applicable_models=applicable_models)
