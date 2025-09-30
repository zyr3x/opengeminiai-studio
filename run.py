"""
 BelVG LLC.

 NOTICE OF LICENSE

 This source file is subject to the EULA
 that is bundled with this package in the file LICENSE.txt.
 It is also available through the world-wide-web at this URL:
 https://store.belvg.com/BelVG-LICENSE-COMMUNITY.txt

 *******************************************************************
 @category   BelVG
 @author     Oleg Semenov
 @copyright  Copyright (c) BelVG LLC. (http://www.belvg.com)
 @license    http://store.belvg.com/BelVG-LICENSE-COMMUNITY.txt

"""
from flask import Flask
from app import run

if __name__ == '__main__':
    app = run(Flask(__name__))

