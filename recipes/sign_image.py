# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for signing ChromeOS images."""

# This recipe is temporarily being used to convert buildbucket jobs to sign a
# cr50_firmware image into signing instructions uploaded to gs.  This will allow
# the Cr50 team to upload signing instructions without needing write access to
# gs://chromeos-releases.

# When image signing starts being scheduled via buildbucket jobs instead of
# uploaded instruction files, the recipe will need to be modified to actually
# sign the image, instead of uploading instructions files.

import os

from PB.recipes.chromeos import sign_image
from PB.recipes.chromeos.sign_image import ArtifactType
from PB.recipes.chromeos.sign_image import Cr50Instructions
from PB.recipes.chromeos.sign_image import SignImageProperties
from PB.recipe_engine import result as result_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

PROPERTIES = SignImageProperties


class _BucketBase(object):
  def __init__(self, bucket, base):
    self.bucket = bucket.strip('/')
    self.base = base.lstrip('/')

  def gs_path(self, *args):
    """Returns the full gs:// path for |name|."""
    path = os.path.join(self.bucket, self.base,
                        *[x.strip('/') for x in args])
    return 'gs://' + path

  def rel_path(self, path=None):
    """Returns the relative path for |name|.

    Args:
      path (str): gs://url to remove the prefix from.

    Returns:
      str: path relative to the bucket prefix.
    """
    assert path.startswith(self.gs_path())
    return path[len(self.gs_path()):]

  def path_in_bucket(self, path):
    """Is this gs:// path in this bucket/base.

    Args:
      path (str): gs:// url to check.

    Returns:
      bool: whether the url is in this bucket/base.
    """
    return path.startswith(self.gs_path())


_signer_buckets = {
    sign_image.SIGNER_PRODUCTION: _BucketBase('chromeos-releases/', '/'),
    sign_image.SIGNER_STAGING:
        _BucketBase('chromeos-releases-test/', '/staging/'),
    sign_image.SIGNER_DEV: _BucketBase('chromeos-releases-test/', '/dev/'),
}

# Map cr50_instructions.target to the text value for instructions.
# Capitals with underscores becomes CamelCase, with a couple of exceptions.
_target_type_to_name = {
    v: (k.title().replace('_', '').replace('Prepvt', 'PrePVT').
        replace('Unspecified', 'Unchanged'))
    for k, v in Cr50Instructions.Target.items()
}

def RunSteps(api, properties):
  """Run steps."""
  local_dir = api.path['cleanup']

  with api.step.nest('validate request') as step:
    artifact_type = properties.artifact_type
    artifact_type_name = ArtifactType.Name(
        artifact_type).replace('ARTIFACT_TYPE_', '').lower()
    # TODO(lamontjones): Extend this to checking the config for the list of
    # permitted artifact_types.  Today, only cr50_firmware is permitted.
    if artifact_type != sign_image.ARTIFACT_TYPE_CR50_FIRMWARE:
      return result_pb2.RawResult(
          status=common_pb2.FAILURE,
          summary_markdown='illegal artifact type %s' % (
              ArtifactType.Name(artifact_type)))

    if properties.signer_type == sign_image.SIGNER_UNSPECIFIED:
      signer_type = sign_image.SIGNER_PRODUCTION
    else:
      signer_type = properties.signer_type
    gs = _signer_buckets[signer_type]

    archive = properties.archive
    # The archive must point to a valid location.  In addition to inside their
    # own bucket, any instance is allowed to use the production bucket for
    # images to sign.
    valid_location = (
        gs.path_in_bucket(archive) or
        _signer_buckets[sign_image.SIGNER_PRODUCTION].path_in_bucket(archive))
    if not valid_location:
      return result_pb2.RawResult(
          status=common_pb2.FAILURE,
          summary_markdown='illegal archive location: %s' % archive)

    # Cr50 specific handling.
    cr50 = properties.cr50_instructions
    if cr50.target == Cr50Instructions.NODE_LOCKED and not cr50.device_id:
      return result_pb2.RawResult(
          status=common_pb2.FAILURE, summary_markdown='must set device_id')

    step.presentation.step_text = 'all properties good'

  with api.step.nest('create Cr50 instructions') as step:
    target = _target_type_to_name[cr50.target]

    if not gs.path_in_bucket(archive):
      # TODO(lamontjones): Copy archive to the right place, and adjust archive
      # to be in the proper bucket.
      return result_pb2.RawResult(
          status=common_pb2.FAILURE,
          summary_markdown='TODO: support prod artifacts in staging/dev')

    archive_base = os.path.basename(archive)

    # These are required to be in the instructions file, but are not actually
    # used in Cr50 signing.  They would need to be passed in via properties if
    # we decide that we need them.
    milestone = 'RNone'
    version = 'Unknown'
    versionrev = '%s-%s' % (milestone, version)

    insns = [
        '[general]',
        'archive = %s' % archive_base,
        'board = %s' % properties.build_target.name,
        'type = %s' % artifact_type_name,
        'milestone = %s' % milestone,
        'version = %s' % version,
        'versionrev = %s' % versionrev,
        '[insns]',
        'keyset = %s' % properties.keyset,
        'target = %s' % target,
    ]
    if target == 'NodeLocked':
      insns.append('device_id = %s' % cr50.device_id)

  with api.step.nest('upload cr50 instructions') as step:
    content = str('\n'.join(insns) + '\n')
    insn_basename = 'ChromeOS-%s-%s-%s.instructions' % (
        artifact_type_name, versionrev, properties.keyset)
    local_insn = local_dir.join(insn_basename)
    insn_path = os.path.join(os.path.dirname(archive), insn_basename)
    rel_insn_path = gs.rel_path(insn_path)

    api.file.write_raw(
        name='instructions file', dest=local_insn, data=content)

    api.gsutil(['cp', local_insn, insn_path])
    step.presentation.step_text = 'instructions uploaded'

  with api.step.nest('trigger cr50 signing') as step:
    # TODO(lamontjones): Put some info there instead of /dev/null.
    trigger_data = r''
    trigger_base = '50,' + rel_insn_path.replace('/', ',')
    trigger_path = gs.gs_path('tobesigned', trigger_base)

    local_trigger = local_dir.join(trigger_base)
    api.file.write_raw(
        name='trigger file', dest=local_trigger, data=trigger_data)
    api.gsutil(['cp', local_trigger, trigger_path])
    step.presentation.step_text = 'trigger uploaded'

def GenTests(api):
  yield api.test('basic')

  yield (
      api.test('Cr50') +
      api.properties(SignImageProperties(
          artifact_type=sign_image.ARTIFACT_TYPE_CR50_FIRMWARE,
          keyset='cr50-accessory-mp',
          archive=('gs://chromeos-releases/canary-channel/eve/12499.10.0/'
                   'ChromeOS-cr50_firmware-R78-12499.10.0-eve.tar.bz2'))))

  yield (
      api.test('Cr50_bad_path') +
      api.properties(SignImageProperties(
          artifact_type=sign_image.ARTIFACT_TYPE_CR50_FIRMWARE,
          keyset='cr50-accessory-mp',
          archive=('gs://chromeos-releases-test/canary-channel/eve/12499.10.0/'
                   'ChromeOS-cr50_firmware-R78-12499.10.0-eve.tar.bz2'))))

  yield (
      api.test('Cr50_staging_with_prod_path') +
      api.properties(SignImageProperties(
          signer_type=sign_image.SIGNER_STAGING,
          artifact_type=sign_image.ARTIFACT_TYPE_CR50_FIRMWARE,
          keyset='cr50-accessory-mp',
          archive=('gs://chromeos-releases/canary-channel/eve/12499.10.0/'
                   'ChromeOS-cr50_firmware-R78-12499.10.0-eve.tar.bz2'))))

  yield (
      api.test('cr50_NodeLocked_no_device_id') +
      api.properties(SignImageProperties(
          artifact_type=sign_image.ARTIFACT_TYPE_CR50_FIRMWARE,
          keyset='cr50-accessory-mp',
          archive=('gs://chromeos-releases/canary-channel/eve/12499.10.0/'
                   'ChromeOS-cr50_firmware-R78-12499.10.0-eve.tar.bz2'),
          cr50_instructions=Cr50Instructions(
              target=Cr50Instructions.NODE_LOCKED))))

  yield (
      api.test('cr50_NodeLocked') +
      api.properties(SignImageProperties(
          artifact_type=sign_image.ARTIFACT_TYPE_CR50_FIRMWARE,
          archive=('gs://chromeos-releases/canary-channel/eve/12499.10.0/'
                   'ChromeOS-cr50_firmware-R78-12499.10.0-eve.tar.bz2'),
          keyset='cr50-accessory-mp',
          cr50_instructions=Cr50Instructions(
              target=Cr50Instructions.NODE_LOCKED,
              device_id='12345678-11223344'))))
