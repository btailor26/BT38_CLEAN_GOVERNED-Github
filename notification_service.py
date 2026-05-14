# Notification service for reorder alerts - integrates with Twilio and SendGrid
import os
import logging
from datetime import datetime
from typing import List, Dict, Optional
from twilio.rest import Client
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content

logger = logging.getLogger(__name__)

class NotificationService:
    """Service for sending reorder alerts via email and WhatsApp/SMS"""
    
    def __init__(self):
        # Twilio configuration
        self.twilio_account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        self.twilio_auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        self.twilio_phone_number = os.environ.get("TWILIO_PHONE_NUMBER")
        
        # SendGrid configuration
        self.sendgrid_api_key = os.environ.get("SENDGRID_API_KEY")
        
        # Initialize clients
        self.twilio_client = None
        self.sendgrid_client = None
        
        self._init_clients()
    
    def _init_clients(self):
        """Initialize messaging clients if credentials are available"""
        try:
            if all([self.twilio_account_sid, self.twilio_auth_token, self.twilio_phone_number]):
                self.twilio_client = Client(self.twilio_account_sid, self.twilio_auth_token)
                logger.info("Twilio client initialized successfully")
            else:
                logger.warning("Twilio credentials not configured - SMS/WhatsApp alerts disabled")
                
            if self.sendgrid_api_key:
                self.sendgrid_client = SendGridAPIClient(self.sendgrid_api_key)
                logger.info("SendGrid client initialized successfully")
            else:
                logger.warning("SendGrid API key not configured - email alerts disabled")
                
        except Exception as e:
            logger.error(f"Error initializing notification clients: {e}")
    
    def send_whatsapp_alert(self, to_number: str, message: str) -> bool:
        """Send WhatsApp message via Twilio"""
        if not self.twilio_client:
            logger.error("Twilio client not initialized - cannot send WhatsApp message")
            return False
            
        try:
            # Format number for WhatsApp
            whatsapp_number = f"whatsapp:{to_number}"
            whatsapp_from = f"whatsapp:{self.twilio_phone_number}"
            
            msg_result = self.twilio_client.messages.create(
                body=message,
                from_=whatsapp_from,
                to=whatsapp_number
            )
            
            logger.info(f"WhatsApp message sent successfully - SID: {msg_result.sid}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send WhatsApp message: {e}")
            return False
    
    def send_sms_alert(self, to_number: str, message: str) -> bool:
        """Send SMS message via Twilio"""
        if not self.twilio_client:
            logger.error("Twilio client not initialized - cannot send SMS")
            return False
            
        try:
            msg_result = self.twilio_client.messages.create(
                body=message,
                from_=self.twilio_phone_number,
                to=to_number
            )
            
            logger.info(f"SMS sent successfully - SID: {msg_result.sid}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send SMS: {e}")
            return False
    
    def send_email_alert(self, to_email: str, from_email: str, subject: str, 
                        text_content: Optional[str] = None, html_content: Optional[str] = None) -> bool:
        """Send email alert via SendGrid"""
        if not self.sendgrid_client:
            logger.error("SendGrid client not initialized - cannot send email")
            return False
            
        try:
            message = Mail(
                from_email=Email(from_email),
                to_emails=To(to_email),
                subject=subject
            )
            
            if html_content:
                message.content = Content("text/html", html_content)
            elif text_content:
                message.content = Content("text/plain", text_content)
            else:
                logger.error("No email content provided")
                return False
            
            response = self.sendgrid_client.send(message)
            status_code = getattr(response, 'status_code', 0)
            
            if status_code >= 200 and status_code < 300:
                logger.info(f"Email sent successfully - Status: {status_code}")
                return True
            else:
                response_body = getattr(response, 'body', 'No response body')
                logger.error(f"SendGrid returned error status {status_code}: {response_body}")
                return False
            
        except Exception as e:
            logger.error(f"Failed to send email - Error: {str(e)}")
            error_body = getattr(e, 'body', None)
            if error_body:
                logger.error(f"SendGrid error details: {error_body}")
            return False
    
    def create_reorder_alert_message(self, low_stock_items: List[Dict]) -> str:
        """Create formatted message for low stock alerts"""
        if not low_stock_items:
            return ""
            
        message = f"🔔 LOW STOCK ALERT - {len(low_stock_items)} items need reordering:\\n\\n"
        
        for item in low_stock_items:
            sku = item.get('sku', 'Unknown')
            name = item.get('name', 'Unknown Item')
            current_qty = item.get('quantity', 0)
            reorder_point = item.get('reorder_point', 0)
            
            message += f"📦 {name} (SKU: {sku})\\n"
            message += f"   Current: {current_qty} | Reorder at: {reorder_point}\\n\\n"
        
        message += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        return message
    
    def create_reorder_alert_email(self, low_stock_items: List[Dict]) -> tuple:
        """Create formatted email content for low stock alerts"""
        if not low_stock_items:
            return "", ""
            
        subject = f"Low Stock Alert - {len(low_stock_items)} items need reordering"
        
        # Text content
        text_content = self.create_reorder_alert_message(low_stock_items)
        
        # HTML content
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; margin: 20px;">
            <h2 style="color: #dc3545;">🔔 Low Stock Alert</h2>
            <p>The following {len(low_stock_items)} items have reached their reorder point:</p>
            
            <table style="border-collapse: collapse; width: 100%; margin: 20px 0;">
                <thead>
                    <tr style="background-color: #f8f9fa;">
                        <th style="border: 1px solid #ddd; padding: 12px; text-align: left;">Item</th>
                        <th style="border: 1px solid #ddd; padding: 12px; text-align: left;">SKU</th>
                        <th style="border: 1px solid #ddd; padding: 12px; text-align: center;">Current Stock</th>
                        <th style="border: 1px solid #ddd; padding: 12px; text-align: center;">Reorder Point</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for item in low_stock_items:
            name = item.get('name', 'Unknown Item')
            sku = item.get('sku', 'Unknown')
            current_qty = item.get('quantity', 0)
            reorder_point = item.get('reorder_point', 0)
            
            row_color = "#fff2f2" if current_qty == 0 else "#fff8f0"
            
            html_content += f"""
                    <tr style="background-color: {row_color};">
                        <td style="border: 1px solid #ddd; padding: 8px;">{name}</td>
                        <td style="border: 1px solid #ddd; padding: 8px; font-family: monospace;">{sku}</td>
                        <td style="border: 1px solid #ddd; padding: 8px; text-align: center; font-weight: bold; color: {'#dc3545' if current_qty == 0 else '#fd7e14'};">{current_qty}</td>
                        <td style="border: 1px solid #ddd; padding: 8px; text-align: center;">{reorder_point}</td>
                    </tr>
            """
        
        html_content += f"""
                </tbody>
            </table>
            
            <p style="color: #6c757d; font-size: 12px; margin-top: 30px;">
                Generated on {datetime.now().strftime('%Y-%m-%d at %H:%M:%S')}
            </p>
        </body>
        </html>
        """
        
        return text_content, html_content
    
    def send_reorder_alerts(self, low_stock_items: List[Dict], 
                           notification_settings: Dict) -> Dict:
        """Send reorder alerts via configured channels"""
        results = {
            'whatsapp': False,
            'sms': False,
            'email': False,
            'message': ''
        }
        
        if not low_stock_items:
            results['message'] = 'No items need reordering'
            return results
        
        # Prepare messages
        text_message = self.create_reorder_alert_message(low_stock_items)
        text_content, html_content = self.create_reorder_alert_email(low_stock_items)
        
        # Send WhatsApp if configured
        if notification_settings.get('whatsapp_enabled') and notification_settings.get('whatsapp_number'):
            results['whatsapp'] = self.send_whatsapp_alert(
                notification_settings['whatsapp_number'], 
                text_message
            )
        
        # Send SMS if configured  
        if notification_settings.get('sms_enabled') and notification_settings.get('sms_number'):
            results['sms'] = self.send_sms_alert(
                notification_settings['sms_number'],
                text_message
            )
        
        # Send Email if configured
        if notification_settings.get('email_enabled') and notification_settings.get('email_address'):
            from_email = notification_settings.get('from_email', 'inventory@example.com')
            results['email'] = self.send_email_alert(
                notification_settings['email_address'],
                from_email,
                f"Low Stock Alert - {len(low_stock_items)} items need reordering",
                text_content,
                html_content
            )
        
        # Generate results message
        sent_channels = [channel for channel, success in results.items() 
                        if channel != 'message' and success]
        
        if sent_channels:
            results['message'] = f"Alerts sent via: {', '.join(sent_channels)}"
        else:
            results['message'] = 'No alerts sent - check notification settings'
        
        return results

# Global notification service instance
notification_service = NotificationService()