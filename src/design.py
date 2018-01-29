""" Latin-hypercube parameter design """

import itertools
import logging
from pathlib import Path
import re
import subprocess

import numpy as np

from . import cachedir, parse_system


def generate_lhs(npoints, ndim, seed):
    """
    Generate a maximin LHS.

    """
    logging.debug(
        'generating maximin LHS: '
        'npoints = %d, ndim = %d, seed = %d',
        npoints, ndim, seed
    )

    cachefile = (
        cachedir / 'lhs' /
        'npoints{}_ndim{}_seed{}.npy'.format(npoints, ndim, seed)
    )

    if cachefile.exists():
        logging.debug('loading from cache')
        lhs = np.load(cachefile)
    else:
        logging.debug('not found in cache, generating using R')
        proc = subprocess.run(
            ['R', '--slave'],
            input="""
            library('lhs')
            set.seed({})
            write.table(maximinLHS({}, {}), col.names=FALSE, row.names=FALSE)
            """.format(seed, npoints, ndim).encode(),
            stdout=subprocess.PIPE,
            check=True
        )

        lhs = np.array(
            [l.split() for l in proc.stdout.splitlines()],
            dtype=float
        )

        cachefile.parent.mkdir(exist_ok=True)
        np.save(cachefile, lhs)

    return lhs


class Design:
    """
    Latin-hypercube model design.

    Creates a design for the given system with the given number of points.
    Creates the main (training) design if `validation` is false (default);
    creates the validation design if `validation` is true.  If `seed` is not
    given, a default random seed is used (different defaults for the main and
    validation designs).

    Public attributes:

        system: the system string
        projectiles, beam energy: system projectile pair and beam energy
        type: 'main' or 'validation'
        keys: list of parameter keys
        labels: list of parameter display labels (for TeX / matplotlib)
        range: list of parameter (min, max) tuples
        min, max: np.arrays of parameter min and max
        ndim: number of parameters (i.e. dimensions)
        points: list of design point names (formatted numbers)
        array: the actual design array

    The class also implicitly converts to np.array.

    Public methods:

        write_files: creates input files for running events

    This is probably the worst class in this project, and certainly the least
    generic.  It will probably need to be heavily edited for use in any other
    project, if not completely rewritten.

    """
    def __init__(self, system, npoints=60, validation=False, seed=None):
        self.system = system
        self.projectiles, self.beam_energy = parse_system(system)
        self.type = 'validation' if validation else 'main'

        self.keys, labels, self.range = map(list, zip(*[
            ('grid_scale',    r'grid scale', (0.1, 0.5)),  
            ('parton_struct', r'\chi',       (0.0, 1.0)),
        ]))

        # convert labels into TeX:
        #   - wrap normal text with \mathrm{}
        #   - escape spaces
        #   - surround with $$
        self.labels = [
            re.sub(r'({[A-Za-z]+})', r'\mathrm\1', i)
            .replace(' ', r'\ ')
            .join('$$')
            for i in labels
        ]

        self.ndim = len(self.range)
        self.min, self.max = map(np.array, zip(*self.range))

        # use padded numbers for design point names
        fmt = '{:0' + str(len(str(npoints - 1))) + 'd}'
        self.points = [fmt.format(i) for i in range(npoints)]

        lhsmin = self.min.copy()

        if seed is None:
            seed = 751783496 if validation else 450829120

        self.array = lhsmin + (self.max - lhsmin)*generate_lhs(
            npoints=npoints, ndim=self.ndim, seed=seed
        )


    def __array__(self):
        return self.array

    _template = ''.join(
        '{} = {}\n'.format(key, ' '.join(args)) for (key, *args) in
        [[
            'collision-system', '{collision_system}',
        ], [
            'grid-scale', '{grid_scale}',
        ], [
            'parton-width', '{parton_width}',
        ], [
            'trento-args',
            '--cross-section 7.0',
            '--normalization 20.',
            '--reduced-thickness 0.',
            '--fluctuation {fluct}',
            '--nucleon-min-dist 1.2',
            '--nucleon-width 0.88',
            '--parton-number 3',
        ], [
            'tau-fs', '0.5',
        ], [
            'hydro-args',
            'etas_min=0.08',
            'etas_slope=1.113',
            'etas_curv=-0.479',
            'zetas_max=0.052',
            'zetas_width=0.022',
            'zetas_t0=0.183',
        ], [
            'Tswitch', '0.151',
        ]]
    )

    def write_files(self, basedir):
        """
        Write input files for each design point to `basedir`.

        """
        outdir = basedir / self.type / self.system
        outdir.mkdir(parents=True, exist_ok=True)

        for point, row in zip(self.points, self.array):
            kwargs = dict(
                zip(self.keys, row),
                projectiles=self.projectiles,
                cross_section={
                    # sqrt(s) [GeV] : sigma_NN [fm^2]
                    200: 4.2,
                    2760: 6.4,
                    5020: 7.0,
                }[self.beam_energy]
            )

            # parton number
            parton_number = 3
            nucleon_width = 0.88
            x_struct = kwargs.pop('parton_struct') if parton_number > 1 else 1
            vmin, vmax = (0.2, nucleon_width)
            parton_width = vmin + x_struct*(vmax - vmin)

            # parton fluctuations
            fluct_std = np.sqrt(parton_number)

            kwargs.update(
                fluct=1/fluct_std**2,
                parton_number=parton_number,
                parton_width=min(parton_width, nucleon_width),
            )
            filepath = outdir / point
            with filepath.open('w') as f:
                f.write(self._template.format(**kwargs))
                logging.debug('wrote %s', filepath)


def main():
    import argparse
    from . import systems

    parser = argparse.ArgumentParser(description='generate design input files')
    parser.add_argument(
        'inputs_dir', type=Path,
        help='directory to place input files'
    )
    args = parser.parse_args()

    for system, validation in itertools.product(systems, [False, True]):
        Design(system, validation=validation).write_files(args.inputs_dir)

    logging.info('wrote all files to %s', args.inputs_dir)


if __name__ == '__main__':
    main()
