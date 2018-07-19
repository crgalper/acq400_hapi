import argparse

class intSIAction(argparse.Action):
    def __init__ (self, option_strings, decimal=True, *args, **kwargs):
        super(intSIAction, self).__init__(option_strings=option_strings,
                *args, **kwargs)
        self.decimal = decimal

    def intSI(self, value):
        x = str(value)
        units = x.find('M')
        if units >= 0:
            return int(x[0:units]) * (1000000 if self.decimal else 0x100000)
        else:
            units = x.find('k')
            if units >= 0:
                return int(x[0:units]) * (1000 if self.decimal else 0x400)
            else:
                return int(x)

    def __call__(self, parser, args, value, option_string=None):
       setattr(args, self.dest, self.intSI(value))
        

# unit test
#[pgm@hoy5 acq400_hapi]$ python acq400_hapi/intSIAction.py -d 20M -b 20M
#Hello args.decval 20000000
#Hello args.binval 20971520

if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('-d', '--decval', action=intSIAction)
    parser.add_argument('-b', '--binval', action=intSIAction, decimal=False)

    args = parser.parse_args()

    print("Hello args.decval {}".format(args.decval))
    print("Hello args.binval {}".format(args.binval))

