import numpy as np
from ..adv.rotate import earth2principal

deg2rad = np.pi / 180.


def calc_beam_rotmatrix(theta=20, convex=True, degrees=True):
    """Calculate the rotation matrix from beam coordinates to
    instrument head coordinates.

    Parameters
    ----------
    theta : is the angle of the heads (usually 20 or 30 degrees)

    convex : is a flag for convex or concave head configuration.

    degrees : is a flag which specifies whether theta is in degrees
        or radians (default: degrees=True)
    """
    if degrees:
        theta = theta * deg2rad
    if convex == 0 or convex == -1:
        c = -1
    else:
        c = 1
    a = 1 / (2. * np.sin(theta))
    b = 1 / (4. * np.cos(theta))
    d = a / (2. ** 0.5)
    return np.array([[c * a, -c * a, 0, 0],
                     [0, 0, -c * a, c * a],
                     [b, b, b, b],
                     [d, d, -d, -d]])


def _cat4rot(tpl):
    tmp = []
    for vl in tpl:
        tmp.append(vl[:, None, :])
    return np.concatenate(tuple(tmp), axis=1)


def beam2inst(adcpo, reverse=False, force=False):
    """Rotate velocitiesfrom beam to instrument coordinates.

    Parameters
    ----------
    adpo : The ADP object containing the data.

    reverse : bool (default: False)
           If True, this function performs the inverse rotation
           (inst->beam).
    force : bool (default: False)
        When true do not check which coordinate system the data is in
        prior to performing this rotation.
    """
    if not force:
        if not reverse and adcpo.props['coord_sys'].lower() != 'beam':
            raise ValueError('The input must be in beam coordinates.')
        if reverse and adcpo.props['coord_sys'] != 'inst':
            raise ValueError('The input must be in inst coordinates.')
    if hasattr(adcpo.config, 'rotmat'):
        rotmat = adcpo.config.rotmat
    elif 'TransMatrix' in adcpo.config:
        rotmat = adcpo.config['TransMatrix']
    else:
        rotmat = calc_beam_rotmatrix(adcpo.config.beam_angle,
                                     adcpo.config.beam_pattern == 'convex')
    cs = 'inst'
    if reverse:
        # Can't use transpose because rotation is not between
        # orthogonal coordinate systems
        rotmat = np.linalg.inv(rotmat)
        cs = 'beam'
    adcpo['vel'] = np.einsum('ij,jkl->ikl', rotmat, adcpo['vel'])
    adcpo.props['coord_sys'] = cs


def inst2earth(adcpo, reverse=False,
               fixed_orientation=False, force=False):
    """Rotate velocities from the instrument to earth coordinates.

    This function also rotates data from the 'ship' frame, into the
    earth frame when it is in the ship frame (and
    ``adcpo.config['use_pitchroll'] == 'yes'``). It does not support the
    'reverse' rotation back into the ship frame.

    Parameters
    ----------
    adpo : The ADP object containing the data.

    reverse : bool (default: False)
           If True, this function performs the inverse rotation
           (earth->inst).
    fixed_orientation : bool (default: False)
        When true, take the average orientation and apply it over the
        whole record.
    force : bool (default: False)
        When true do not check which coordinate system the data is in
        prior to performing this rotation.

    Notes
    -----
    The rotation matrix is taken from the Teledyne RDI ADCP Coordinate
    Transformation manual January 2008

    When performing the forward rotation, this function sets the
    'inst2earth:fixed' flag to the value of `fixed_orientation`. When
    performing the reverse rotation, that value is 'popped' from the
    props dict and the input value to this function
    `fixed_orientation` has no effect. If `'inst2earth:fixed'` is not
    in the props dict than the input value *is* used.
    """
    if not force:
        if (not reverse and
                adcpo.props['coord_sys'] not in ['inst', 'ship']):
            raise ValueError("The input must be in 'inst' or 'ship' "
                             "coordinates.")
        if (reverse and
                adcpo.props['coord_sys'].lower() not in ['earth', 'enu']):
            raise ValueError('The input must be in earth coordinates.')
    if (not reverse and 'declination' in adcpo.props.keys() and not
            adcpo.props.get('declination_in_heading', False)):
        # Only do this if making the forward rotation.
        adcpo.heading += adcpo.props['declination']
        adcpo.props['declination_in_heading'] = True
    odat = adcpo.orient
    r = odat.roll * deg2rad
    p = np.arctan(np.tan(odat.pitch * deg2rad) * np.cos(r))
    h = odat.heading * deg2rad
    if not adcpo.props['inst_model'].lower() == 'signature':
        if adcpo.config.orientation == 'up':
            r += np.pi
        if (adcpo.props['coord_sys'] == 'ship' and
                adcpo.config['use_pitchroll'] == 'yes'):
            r[:] = 0
            p[:] = 0
    ch = np.cos(h)
    sh = np.sin(h)
    cr = np.cos(r)
    sr = np.sin(r)
    cp = np.cos(p)
    sp = np.sin(p)
    rotmat = np.empty((3, 3, len(r)))
    rotmat[0, 0, :] = ch * cr + sh * sp * sr
    rotmat[0, 1, :] = sh * cp
    rotmat[0, 2, :] = ch * sr - sh * sp * cr
    rotmat[1, 0, :] = -sh * cr + ch * sp * sr
    rotmat[1, 1, :] = ch * cp
    rotmat[1, 2, :] = -sh * sr - ch * sp * cr
    rotmat[2, 0, :] = -cp * sr
    rotmat[2, 1, :] = sp
    rotmat[2, 2, :] = cp * cr
    if adcpo.props['inst_model'].lower() == 'signature':
        if np.any(odat['orient_up'] != 4):
            raise Exception("Orientations other than 'ZUP' are "
                            "not yet supported.")
        # # 0: 'XUP', heading: Z
        # inds = odat['orient_up'] == 0
        # # 1: 'XDOWN', heading: Z
        # inds = odat['orient_up'] == 1
        # # 4: 'ZUP', heading: X
        # # This is the ENU case, I think.

    # Only operate on the first 3-components, b/c the 4th is err_vel
    ess = 'ijt,jdt->idt'
    cs = 'earth'
    if reverse:
        cs = 'inst'
        fixed_orientation = adcpo.props.pop('inst2earth:fixed',
                                            fixed_orientation)
        ess = ess.replace('ij', 'ji')
    else:
        adcpo.props['inst2earth:fixed'] = fixed_orientation
    if fixed_orientation:
        ess = ess.replace('t,', ',')
        rotmat = rotmat.mean(-1)
    adcpo['vel'][:3] = np.einsum(ess, rotmat, adcpo['vel'][:3])
    if 'bt_vel' in adcpo:
        adcpo['bt_vel'][:3] = np.einsum(ess.replace('d', ''),
                                        rotmat, adcpo['bt_vel'][:3])
    adcpo.props['coord_sys'] = cs


def inst2earth_heading(adpo):
    h = adpo.orient.heading[:] * deg2rad
    if 'heading_offset' in adpo.props.keys():
        h += adpo.props['heading_offset'] * deg2rad
    if 'declination' in adpo.props.keys():
        h += adpo.props['declination'] * deg2rad
    return np.exp(-1j * h)
