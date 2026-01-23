const nodemailer = require('nodemailer');

// Create transporter
const createTransporter = () => {
  return nodemailer.createTransporter({
    host: process.env.SMTP_HOST,
    port: process.env.SMTP_PORT,
    secure: process.env.SMTP_PORT === '465', // true for 465, false for other ports
    auth: {
      user: process.env.SMTP_USER,
      pass: process.env.SMTP_PASS
    }
  });
};

// Send welcome email
const sendWelcomeEmail = async (user) => {
  try {
    const transporter = createTransporter();
    
    const mailOptions = {
      from: process.env.EMAIL_FROM,
      to: user.email,
      subject: 'Welcome to PowerPlay! 🎬',
      html: `
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
          <h1 style="color: #6366f1;">Welcome to PowerPlay!</h1>
          <p>Hi ${user.name},</p>
          <p>Welcome to PowerPlay! We're excited to help you transform your sports videos into professional highlights using AI.</p>
          <p>Here's what you can do with PowerPlay:</p>
          <ul>
            <li>Upload sports videos</li>
            <li>Automatically detect players and key moments</li>
            <li>Generate professional highlights</li>
            <li>Share your highlights with teammates and coaches</li>
          </ul>
          <p>Ready to get started? Upload your first video and see the magic happen!</p>
          <a href="${process.env.FRONTEND_URL}/upload" style="background-color: #6366f1; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">Upload Your First Video</a>
          <p>Best regards,<br>The PowerPlay Team</p>
        </div>
      `
    };

    const result = await transporter.sendMail(mailOptions);
    console.log('Welcome email sent:', result.messageId);
    return result;
  } catch (error) {
    console.error('Welcome email error:', error);
    throw new Error('Failed to send welcome email');
  }
};

// Send analysis completion email
const sendAnalysisCompleteEmail = async (user, analysis) => {
  try {
    const transporter = createTransporter();
    
    const mailOptions = {
      from: process.env.EMAIL_FROM,
      to: user.email,
      subject: 'Your video analysis is complete! 🎉',
      html: `
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
          <h1 style="color: #6366f1;">Analysis Complete!</h1>
          <p>Hi ${user.name},</p>
          <p>Great news! Your video analysis is complete and ready for review.</p>
          <div style="background-color: #f3f4f6; padding: 20px; border-radius: 8px; margin: 20px 0;">
            <h3>Analysis Summary:</h3>
            <ul>
              <li>Analysis ID: ${analysis.id}</li>
              <li>Status: ${analysis.status}</li>
              <li>Players detected: ${analysis.results?.faces?.length || 0}</li>
              <li>Key moments found: ${analysis.results?.detections?.length || 0}</li>
            </ul>
          </div>
          <p>Ready to generate highlights? Click the button below to view your results and create amazing highlights!</p>
          <a href="${process.env.FRONTEND_URL}/dashboard" style="background-color: #6366f1; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">View Results</a>
          <p>Best regards,<br>The PowerPlay Team</p>
        </div>
      `
    };

    const result = await transporter.sendMail(mailOptions);
    console.log('Analysis complete email sent:', result.messageId);
    return result;
  } catch (error) {
    console.error('Analysis complete email error:', error);
    throw new Error('Failed to send analysis complete email');
  }
};

// Send highlight ready email
const sendHighlightReadyEmail = async (user, highlight) => {
  try {
    const transporter = createTransporter();
    
    const mailOptions = {
      from: process.env.EMAIL_FROM,
      to: user.email,
      subject: 'Your highlights are ready! 🏆',
      html: `
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
          <h1 style="color: #6366f1;">Highlights Ready!</h1>
          <p>Hi ${user.name},</p>
          <p>Your highlights are ready for download! We've created an amazing compilation of the best moments from your video.</p>
          <div style="background-color: #f3f4f6; padding: 20px; border-radius: 8px; margin: 20px 0;">
            <h3>Highlight Details:</h3>
            <ul>
              <li>Highlight ID: ${highlight.id}</li>
              <li>Duration: ${highlight.duration}</li>
              <li>Type: ${highlight.type}</li>
              <li>Clips: ${highlight.clips}</li>
            </ul>
          </div>
          <p>Click the button below to download your highlights and share them with your team!</p>
          <a href="${process.env.FRONTEND_URL}/highlights/${highlight.id}" style="background-color: #6366f1; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">Download Highlights</a>
          <p>Best regards,<br>The PowerPlay Team</p>
        </div>
      `
    };

    const result = await transporter.sendMail(mailOptions);
    console.log('Highlight ready email sent:', result.messageId);
    return result;
  } catch (error) {
    console.error('Highlight ready email error:', error);
    throw new Error('Failed to send highlight ready email');
  }
};

// Send password reset email
const sendPasswordResetEmail = async (user, resetToken) => {
  try {
    const transporter = createTransporter();
    
    const resetUrl = `${process.env.FRONTEND_URL}/reset-password?token=${resetToken}`;
    
    const mailOptions = {
      from: process.env.EMAIL_FROM,
      to: user.email,
      subject: 'Reset your PowerPlay password',
      html: `
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
          <h1 style="color: #6366f1;">Password Reset Request</h1>
          <p>Hi ${user.name},</p>
          <p>We received a request to reset your password. Click the button below to create a new password:</p>
          <a href="${resetUrl}" style="background-color: #6366f1; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">Reset Password</a>
          <p>If you didn't request this password reset, you can safely ignore this email.</p>
          <p>This link will expire in 1 hour.</p>
          <p>Best regards,<br>The PowerPlay Team</p>
        </div>
      `
    };

    const result = await transporter.sendMail(mailOptions);
    console.log('Password reset email sent:', result.messageId);
    return result;
  } catch (error) {
    console.error('Password reset email error:', error);
    throw new Error('Failed to send password reset email');
  }
};

// Send account verification email
const sendVerificationEmail = async (user, verificationToken) => {
  try {
    const transporter = createTransporter();
    
    const verificationUrl = `${process.env.FRONTEND_URL}/verify-email?token=${verificationToken}`;
    
    const mailOptions = {
      from: process.env.EMAIL_FROM,
      to: user.email,
      subject: 'Verify your PowerPlay account',
      html: `
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
          <h1 style="color: #6366f1;">Verify Your Account</h1>
          <p>Hi ${user.name},</p>
          <p>Welcome to PowerPlay! Please verify your email address by clicking the button below:</p>
          <a href="${verificationUrl}" style="background-color: #6366f1; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">Verify Email</a>
          <p>If you didn't create an account with PowerPlay, you can safely ignore this email.</p>
          <p>Best regards,<br>The PowerPlay Team</p>
        </div>
      `
    };

    const result = await transporter.sendMail(mailOptions);
    console.log('Verification email sent:', result.messageId);
    return result;
  } catch (error) {
    console.error('Verification email error:', error);
    throw new Error('Failed to send verification email');
  }
};

// Send subscription update email
const sendSubscriptionUpdateEmail = async (user, subscription) => {
  try {
    const transporter = createTransporter();
    
    const mailOptions = {
      from: process.env.EMAIL_FROM,
      to: user.email,
      subject: 'Your PowerPlay subscription has been updated',
      html: `
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
          <h1 style="color: #6366f1;">Subscription Updated</h1>
          <p>Hi ${user.name},</p>
          <p>Your PowerPlay subscription has been updated successfully.</p>
          <div style="background-color: #f3f4f6; padding: 20px; border-radius: 8px; margin: 20px 0;">
            <h3>Subscription Details:</h3>
            <ul>
              <li>Plan: ${subscription.plan}</li>
              <li>Status: ${subscription.status}</li>
              <li>Next billing date: ${subscription.currentPeriodEnd}</li>
            </ul>
          </div>
          <p>Thank you for choosing PowerPlay!</p>
          <p>Best regards,<br>The PowerPlay Team</p>
        </div>
      `
    };

    const result = await transporter.sendMail(mailOptions);
    console.log('Subscription update email sent:', result.messageId);
    return result;
  } catch (error) {
    console.error('Subscription update email error:', error);
    throw new Error('Failed to send subscription update email');
  }
};

module.exports = {
  sendWelcomeEmail,
  sendAnalysisCompleteEmail,
  sendHighlightReadyEmail,
  sendPasswordResetEmail,
  sendVerificationEmail,
  sendSubscriptionUpdateEmail
}; 