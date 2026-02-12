# =============================================================================
# LITTLE NATE — Admin Console (React)
# =============================================================================
FROM node:18-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy source code
COPY . .

# Build for production (optional - for dev we use npm start)
# RUN npm run build

# Expose port
EXPOSE 3000

# Start development server
CMD ["npm", "start"]
