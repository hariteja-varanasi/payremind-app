# WhatsApp templates to submit to Meta

Submit these in WhatsApp Manager once the Business account is verified. Names and variable
order must match the code (`messaging/whatsapp.py`). Approval usually takes minutes to a day.

## `payment_reminder_v1` (category: Utility)

Variables: `{{1}}` customer name, `{{2}}` invoice number, `{{3}}` amount (e.g. ₹12,500.00),
`{{4}}` pay page link.

**English (`en`)**

> Hello {{1}}, this is a reminder that payment for invoice {{2}} of {{3}} is pending. You can pay securely here: {{4}}
>
> Reply STOP to stop these reminders.

**Hindi (`hi`)**

> नमस्ते {{1}}, यह याद दिलाने के लिए है कि इनवॉइस {{2}} के {{3}} का भुगतान बाकी है। आप यहाँ सुरक्षित रूप से भुगतान कर सकते हैं: {{4}}
>
> ये रिमाइंडर बंद करने के लिए STOP लिखकर भेजें।

Have a native Hindi speaker read the Hindi text before you submit it.

Optional: add a quick-reply button with the text `STOP`. The webhook already handles button taps.

## `login_code_v1` (category: Authentication)

Meta writes the body text for authentication templates ("{{1}} is your verification code…").
Choose the **Copy code** button and English. Add Hindi later if beta users ask for it.

## Webhook

Callback URL `https://<your domain>/webhooks/whatsapp`, verify token = `PAYREMIND_WHATSAPP_VERIFY_TOKEN`,
subscribe to the `messages` field. Set `PAYREMIND_WHATSAPP_APP_SECRET` so signatures are checked.
