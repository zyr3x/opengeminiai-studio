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

import app.mcp_handler as mcp_handler
import app.utils as utils
from app.controllers.proxy import proxy_bp
from app.controllers.settings import settings_bp
from app.controllers.web_ui import web_ui_bp
from app.controllers.web_ui_chat import web_ui_chat_bp
app = Flask(__name__)

# Load configurations from external modules
mcp_handler.load_mcp_config()
utils.load_prompt_config()

# Register blueprints
app.register_blueprint(proxy_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(web_ui_bp)
app.register_blueprint(web_ui_chat_bp)

if __name__ == '__main__':
    print("Starting proxy server on http://0.0.0.0:8080...")
    app.run(host='0.0.0.0', port=8081)
