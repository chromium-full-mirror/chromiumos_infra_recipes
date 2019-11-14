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
import string

from PB.chromiumos import sign_image as sign_image_os
from PB.chromiumos import common as common_os
from PB.chromiumos.common import ImageType
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.sign_image import Cr50Instructions
from PB.recipes.chromeos.sign_image import SignImageProperties
from PB.recipe_engine import result as result_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/random',
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
    sign_image_os.SIGNER_PRODUCTION: _BucketBase('chromeos-releases/', '/'),
    sign_image_os.SIGNER_STAGING:
        _BucketBase('chromeos-releases-test/', '/staging/'),
    sign_image_os.SIGNER_DEV: _BucketBase('chromeos-releases-test/', '/dev/'),
}

# Map cr50_instructions.target to the text value for instructions.
# Capitals with underscores becomes CamelCase, with a couple of exceptions.
_target_type_to_name = {
    v: (k.title().replace('_', '').replace('Prepvt', 'PrePVT').
        replace('Unspecified', 'Unchanged'))
    for k, v in Cr50Instructions.Target.items()
}

# Map channel numbers to names.
_channel_to_name = {v: k.lower().replace('channel_', '')
                    for k, v in common_os.Channel.items()}

def RunSteps(api, properties):
  """Run steps."""
  local_dir = api.path['cleanup']

  with api.step.nest('validate request') as step:
    image_type = properties.image_type
    image_type_name = ImageType.Name(image_type).lower()
    # TODO(lamontjones): Extend this to checking the config for the list of
    # permitted image_types.  Today, only cr50_firmware is permitted.
    if image_type != common_os.CR50_FIRMWARE:
      return result_pb2.RawResult(
          status=common_pb2.FAILURE,
          summary_markdown='illegal image type %s' % (
              ImageType.Name(image_type)))

    if properties.signer_type == sign_image_os.SIGNER_UNSPECIFIED:
      signer_type = sign_image_os.SIGNER_PRODUCTION
    else:
      signer_type = properties.signer_type
    gs = _signer_buckets[signer_type]
    prod = _signer_buckets[sign_image_os.SIGNER_PRODUCTION]

    # The archive must point to a valid location.  In addition to inside their
    # own bucket, any instance is allowed to use the production bucket for
    # images to sign.  If needed, copy the archive into the non-prod bucket.
    archive = properties.archive
    if not gs.path_in_bucket(archive):
      if prod.path_in_bucket(archive):
        # We know that the archive is not in OUR bucket, but it is in the prod
        # bucket.  Copy it into place and adjust the archive path.
        new_archive = gs.gs_path(prod.rel_path(archive))
        api.gsutil(['cp', archive, new_archive])
        archive = new_archive
      else:
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
    channel = _channel_to_name[properties.channel]

    archive_base = os.path.basename(archive)

    # These are required to be in the instructions file, but are not actually
    # used in Cr50 signing.  They would need to be passed in via properties if
    # we decide that we need them.
    milestone = 'RNone'
    version = 'Unknown'
    versionrev = '%s-%s' % (milestone, version)
    if properties.build_target.name:
      build_target = properties.build_target.name
    else:
      build_target = 'Unknown'

    insns = [
        '[general]',
        'archive = %s' % archive_base,
        'board = %s' % build_target,
        'type = %s' % image_type_name,
        'milestone = %s' % milestone,
        'version = %s' % version,
        'versionrev = %s' % versionrev,
        '[insns]',
        'channel = %s' % channel,
        'keyset = %s' % properties.keyset,
        'target = %s' % target,
    ]
    if target == 'NodeLocked':
      insns.append(
          'output_names = cr50_@VERSION@_@TARGET@-@DEVICE_ID@_@KEYSET@')
      insns.append('device_id = %s' % cr50.device_id)
    else:
      insns.append('output_names = cr50_@VERSION@_@TARGET@_@KEYSET@')

  with api.step.nest('upload cr50 instructions') as step:
    content = str('\n'.join(insns) + '\n')
    # crbug.com/1025023: Don't clobber other pending instructions files.
    random_suffix = ''.join(api.random.choice(string.ascii_letters)
                            for n in range(8))
    insn_basename = 'ChromeOS-%s-%s-%s-%s.instructions' % (
        image_type_name, versionrev, properties.keyset, random_suffix)
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
          image_type=common_os.CR50_FIRMWARE,
          keyset='cr50-accessory-mp',
          channel=common_os.CHANNEL_CANARY,
          archive=('gs://chromeos-releases/canary-channel/eve/12499.10.0/'
                   'ChromeOS-cr50_firmware-R78-12499.10.0-eve.tar.bz2'))))

  yield (
      api.test('Cr50_bad_path') +
      api.properties(SignImageProperties(
          image_type=common_os.CR50_FIRMWARE,
          keyset='cr50-accessory-mp',
          channel=common_os.CHANNEL_CANARY,
          archive=('gs://chromeos-releases-test/canary-channel/eve/12499.10.0/'
                   'ChromeOS-cr50_firmware-R78-12499.10.0-eve.tar.bz2'))))

  yield (
      api.test('Cr50_staging_with_prod_path') +
      api.properties(SignImageProperties(
          signer_type=sign_image_os.SIGNER_STAGING,
          image_type=common_os.CR50_FIRMWARE,
          build_target=BuildTarget(name='board'),
          keyset='cr50-accessory-mp',
          channel=common_os.CHANNEL_CANARY,
          archive=('gs://chromeos-releases/canary-channel/eve/12499.10.0/'
                   'ChromeOS-cr50_firmware-R78-12499.10.0-eve.tar.bz2'))))

  yield (
      api.test('cr50_NodeLocked_no_device_id') +
      api.properties(SignImageProperties(
          image_type=common_os.CR50_FIRMWARE,
          keyset='cr50-accessory-mp',
          channel=common_os.CHANNEL_CANARY,
          archive=('gs://chromeos-releases/canary-channel/eve/12499.10.0/'
                   'ChromeOS-cr50_firmware-R78-12499.10.0-eve.tar.bz2'),
          cr50_instructions=Cr50Instructions(
              target=Cr50Instructions.NODE_LOCKED))))

  yield (
      api.test('cr50_NodeLocked') +
      api.properties(SignImageProperties(
          image_type=common_os.CR50_FIRMWARE,
          channel=common_os.CHANNEL_CANARY,
          archive=('gs://chromeos-releases/canary-channel/eve/12499.10.0/'
                   'ChromeOS-cr50_firmware-R78-12499.10.0-eve.tar.bz2'),
          keyset='cr50-accessory-mp',
          cr50_instructions=Cr50Instructions(
              target=Cr50Instructions.NODE_LOCKED,
              device_id='12345678-11223344'))))
